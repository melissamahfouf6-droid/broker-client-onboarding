# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html).

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

from .const import GROUP_FINANCE, ensure_group


class BrokerCommissionPlan(models.Model):
    _name = 'broker.commission.plan'
    _description = 'IB Commission Plan'
    _order = 'name, id'

    name = fields.Char(required=True, translate=True)
    active = fields.Boolean(default=True)
    commission_type = fields.Selection(
        selection=[
            ('per_lot', 'Per Lot'),
            ('percent_of_deposit', 'Percent of Deposit'),
        ],
        required=True,
        default='percent_of_deposit',
        help="Per lot pays when a referred client's trade is booked. Percent of deposit pays when a referred deposit is marked done.",
    )
    rate = fields.Float(
        required=True,
        digits=(16, 4),
        help="Per lot: amount in the company currency for each lot. Percent of deposit: 8 means eight percent of the deposit.",
    )
    company_id = fields.Many2one(
        'res.company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    currency_id = fields.Many2one(
        'res.currency',
        required=True,
        default=lambda self: self.env.company.currency_id,
    )
    partner_ids = fields.One2many('res.partner', 'commission_plan_id', string='Introducing Brokers')

    _positive_rate = models.Constraint(
        'CHECK(rate > 0)',
        'The commission rate must be greater than zero.',
    )

    @api.constrains('commission_type', 'rate')
    def _check_percent_rate(self):
        for plan in self:
            if plan.commission_type == 'percent_of_deposit' and plan.rate > 100:
                raise ValidationError(self.env._(
                    "A percent-of-deposit plan cannot pay more than 100 percent of the deposit."
                ))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('currency_id'):
                company = self.env['res.company'].browse(vals.get('company_id')) or self.env.company
                vals['currency_id'] = company.currency_id.id
        return super().create(vals_list)


class BrokerIbCommission(models.Model):
    _name = 'broker.ib.commission'
    _description = 'IB Commission'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(required=True, copy=False, readonly=True, default='/')
    ib_partner_id = fields.Many2one(
        'res.partner',
        string='Introducing Broker',
        required=True,
        index=True,
        domain=[('is_introducing_broker', '=', True)],
        tracking=True,
    )
    client_partner_id = fields.Many2one(
        'res.partner',
        string='Client',
        required=True,
        index=True,
        tracking=True,
    )
    plan_id = fields.Many2one('broker.commission.plan', string='Plan', readonly=True)
    source_trade_id = fields.Many2one('broker.trade', string='Trade', ondelete='restrict', readonly=True)
    source_transaction_id = fields.Many2one(
        'broker.transaction',
        string='Deposit',
        ondelete='restrict',
        readonly=True,
    )
    base_amount = fields.Float(
        digits=(16, 4),
        readonly=True,
        help="Deposit amount, or traded volume in lots, depending on the plan.",
    )
    rate = fields.Float(digits=(16, 4), readonly=True, help="Rate copied from the plan when the commission was accrued. Later plan edits do not rewrite it.")
    currency_id = fields.Many2one('res.currency', required=True, readonly=True)
    commission_amount = fields.Monetary(currency_field='currency_id', readonly=True, tracking=True)
    state = fields.Selection(
        selection=[
            ('pending', 'Pending'),
            ('confirmed', 'Confirmed'),
            ('paid', 'Paid'),
        ],
        default='pending',
        required=True,
        tracking=True,
        index=True,
        group_expand=True,
    )
    company_id = fields.Many2one(
        'res.company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )

    _positive_commission = models.Constraint(
        'CHECK(commission_amount >= 0)',
        'The commission amount cannot be negative.',
    )

    @api.model_create_multi
    def create(self, vals_list):
        sequence = self.env['ir.sequence'].sudo()
        for vals in vals_list:
            if vals.get('name', '/') in (False, '/'):
                vals['name'] = sequence.next_by_code('broker.ib.commission') or '/'
        return super().create(vals_list)

    @api.constrains('source_trade_id', 'source_transaction_id', 'ib_partner_id', 'client_partner_id')
    def _check_source(self):
        for commission in self:
            has_trade = bool(commission.source_trade_id)
            has_deposit = bool(commission.source_transaction_id)
            if has_trade == has_deposit:
                raise ValidationError(self.env._(
                    "A commission must reference either a trade or a deposit."
                ))
            if not commission.ib_partner_id.is_introducing_broker:
                raise ValidationError(self.env._(
                    "Commission can only be accrued to an introducing broker."
                ))
            if commission.client_partner_id.introducing_broker_id != commission.ib_partner_id:
                raise ValidationError(self.env._(
                    "%(client)s is not referred by %(ib)s.",
                    client=commission.client_partner_id.display_name,
                    ib=commission.ib_partner_id.display_name,
                ))

    def unlink(self):
        if any(commission.state == 'paid' for commission in self):
            raise UserError(self.env._(
                "A commission that has been marked paid stays on the book and cannot be deleted."
            ))
        return super().unlink()

    def action_confirm(self):
        ensure_group(self.env, GROUP_FINANCE, self.env._(
            "Only a Finance Manager can confirm introducing-broker commission."
        ))
        pending = self.filtered(lambda commission: commission.state == 'pending')
        if not pending:
            raise UserError(self.env._("Select pending commissions to confirm."))
        pending.write({'state': 'confirmed'})
        return True

    def action_mark_paid(self):
        ensure_group(self.env, GROUP_FINANCE, self.env._(
            "Only a Finance Manager can mark introducing-broker commission as paid."
        ))
        if not self:
            raise UserError(self.env._("Select confirmed commissions to mark as paid."))
        if any(commission.state != 'confirmed' for commission in self):
            raise UserError(self.env._(
                "Only confirmed commissions can be marked as paid. Confirm the pending ones first."
            ))
        self.write({'state': 'paid'})
        return True

    @api.model
    def _generate_from_deposit(self, transactions):
        """Accrue percent-of-deposit commission for done deposits of referred clients."""
        for tx in transactions:
            if tx.transaction_type != 'deposit' or tx.state != 'done':
                continue
            client = tx.partner_id or tx.account_id.partner_id
            ib = client.introducing_broker_id
            plan = ib.commission_plan_id
            if not ib or not plan or plan.commission_type != 'percent_of_deposit':
                continue
            if self.search_count([('source_transaction_id', '=', tx.id)]):
                continue
            currency = tx.currency_id
            amount = currency.round(tx.amount * plan.rate / 100.0)
            self.create({
                'ib_partner_id': ib.id,
                'client_partner_id': client.id,
                'plan_id': plan.id,
                'source_transaction_id': tx.id,
                'base_amount': tx.amount,
                'rate': plan.rate,
                'currency_id': currency.id,
                'commission_amount': amount,
                'company_id': tx.company_id.id,
            })

    @api.model
    def _generate_from_trade(self, trades):
        """Accrue per-lot commission for live-account trades of referred clients."""
        for trade in trades:
            if trade.account_id.account_type != 'live':
                continue
            client = trade.partner_id
            ib = client.introducing_broker_id
            plan = ib.commission_plan_id
            if not ib or not plan or plan.commission_type != 'per_lot':
                continue
            if self.search_count([('source_trade_id', '=', trade.id)]):
                continue
            company = trade.company_id or self.env.company
            currency = company.currency_id
            amount = currency.round(trade.volume_lots * plan.rate)
            self.create({
                'ib_partner_id': ib.id,
                'client_partner_id': client.id,
                'plan_id': plan.id,
                'source_trade_id': trade.id,
                'base_amount': trade.volume_lots,
                'rate': plan.rate,
                'currency_id': currency.id,
                'commission_amount': amount,
                'company_id': company.id,
            })
