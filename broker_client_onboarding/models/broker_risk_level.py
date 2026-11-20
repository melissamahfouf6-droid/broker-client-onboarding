# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html).

from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools.float_utils import float_compare


class BrokerRiskLevel(models.Model):
    _name = 'broker.risk.level'
    _description = 'Client Risk Level'
    _order = 'sequence, id'

    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True, help="Stable code used by imports and audits. For example: low, medium, high.")
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Limit Currency',
        required=True,
        default=lambda self: self.env.company.currency_id,
        help="Funding limits and the second-approval threshold are denominated in this currency, normally the company currency.",
    )
    max_leverage = fields.Integer(
        string='Maximum Leverage',
        required=True,
        default=100,
        help="500 means the account may be geared at most 1:500. A higher client risk takes a lower cap.",
    )
    max_single_deposit = fields.Monetary(required=True, currency_field='currency_id')
    max_single_withdrawal = fields.Monetary(required=True, currency_field='currency_id')
    daily_withdrawal_limit = fields.Monetary(
        required=True,
        currency_field='currency_id',
        help="Cap on withdrawal requests submitted today, including those still waiting for approval or payment.",
    )
    second_approval_threshold = fields.Monetary(
        string='Second Approval Threshold',
        required=True,
        currency_field='currency_id',
        help="Amounts strictly above this figure need a Compliance approval and a Finance Manager approval.",
    )
    notes = fields.Text(translate=True)

    _code_uniq = models.Constraint(
        'UNIQUE(code)',
        'The risk level code must be unique.',
    )
    _positive_leverage = models.Constraint(
        'CHECK(max_leverage > 0)',
        'Maximum leverage must be a positive number.',
    )
    _non_negative_limits = models.Constraint(
        'CHECK(max_single_deposit >= 0 AND max_single_withdrawal >= 0 AND daily_withdrawal_limit >= 0 AND second_approval_threshold >= 0)',
        'Funding limits cannot be negative.',
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('currency_id'):
                company = self.env['res.company'].browse(vals.get('company_id')) or self.env.company
                vals['currency_id'] = company.currency_id.id
        return super().create(vals_list)

    @api.constrains('max_single_withdrawal', 'daily_withdrawal_limit', 'currency_id')
    def _check_daily_covers_single(self):
        for level in self:
            rounding = level.currency_id.rounding or 0.01
            if float_compare(level.daily_withdrawal_limit, level.max_single_withdrawal, precision_rounding=rounding) < 0:
                raise ValidationError(self.env._(
                    "On %(level)s the daily withdrawal limit must be at least the single-withdrawal cap. "
                    "Otherwise a withdrawal that passes the single cap can never pass the daily cap.",
                    level=level.name,
                ))
