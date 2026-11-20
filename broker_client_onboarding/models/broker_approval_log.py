# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html).

from odoo import api, fields, models
from odoo.exceptions import UserError


class BrokerApprovalLog(models.Model):
    """Immutable audit trail of KYC reviews and money-movement decisions.

    Rows are created with sudo() from the business methods only. ``write`` and
    ``unlink`` refuse every user, including the superuser, so a later correction
    is a new row and the original decision stays readable for an audit.
    """

    _name = 'broker.approval.log'
    _description = 'Approval Log'
    _order = 'date desc, id desc'
    _rec_name = 'display_label'

    res_model = fields.Char(required=True, index=True)
    res_id = fields.Integer(required=True, index=True)
    transaction_id = fields.Many2one(
        'broker.transaction',
        string='Transaction',
        ondelete='restrict',
        index=True,
        readonly=True,
    )
    kyc_document_id = fields.Many2one(
        'broker.kyc.document',
        string='KYC Document',
        ondelete='restrict',
        index=True,
        readonly=True,
    )
    action = fields.Selection(
        selection=[
            ('submit', 'Submit'),
            ('review', 'Start Review'),
            ('approve', 'Approve'),
            ('reject', 'Reject'),
            ('done', 'Done'),
            ('cancel', 'Cancel'),
            ('expire', 'Expire'),
        ],
        required=True,
        readonly=True,
        index=True,
    )
    level = fields.Integer(
        readonly=True,
        help="1 for the Compliance approval, 2 for the Finance Manager approval. Empty for other actions.",
    )
    user_id = fields.Many2one('res.users', string='User', required=True, readonly=True, index=True)
    date = fields.Datetime(required=True, readonly=True, default=fields.Datetime.now, index=True)
    comment = fields.Text(readonly=True)
    amount = fields.Monetary(readonly=True, currency_field='currency_id', help="Amount of the request at the time of the decision.")
    currency_id = fields.Many2one('res.currency', readonly=True)
    company_id = fields.Many2one('res.company', required=True, readonly=True, index=True)
    display_label = fields.Char(compute='_compute_display_label')

    @api.depends('action', 'res_model', 'res_id', 'level', 'user_id')
    def _compute_display_label(self):
        action_labels = dict(self._fields['action']._description_selection(self.env))
        for entry in self:
            label = action_labels.get(entry.action, entry.action or '')
            if entry.level:
                label = self.env._('%(action)s (level %(level)s)', action=label, level=entry.level)
            entry.display_label = self.env._(
                '%(action)s by %(user)s',
                action=label,
                user=entry.user_id.display_name or '',
            )

    @api.model
    def log_decision(self, record, action, level=0, comment=False, amount=0.0, currency=None):
        """Append one audit row for a transaction or a KYC document.

        Must be called from the business method, before the environment is
        switched to superuser, so the row records the human who decided.
        """
        if record._name not in ('broker.transaction', 'broker.kyc.document'):
            raise UserError(self.env._(
                "The approval log only records funding requests and KYC reviews."
            ))
        company = record.company_id or self.env.company
        currency = currency or getattr(record, 'currency_id', False) or company.currency_id
        vals = {
            'res_model': record._name,
            'res_id': record.id,
            'action': action,
            'level': level or 0,
            'user_id': self.env.user.id,
            'date': fields.Datetime.now(),
            'comment': comment or False,
            'amount': amount or 0.0,
            'currency_id': currency.id,
            'company_id': company.id,
        }
        if record._name == 'broker.transaction':
            vals.update({
                'transaction_id': record.id,
                'amount': record.amount,
                'currency_id': record.currency_id.id,
            })
        else:
            vals['kyc_document_id'] = record.id
        return self.sudo().create(vals)

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su:
            raise UserError(self.env._(
                "Approval log entries are written by the platform when a decision is recorded. "
                "They cannot be created by hand."
            ))
        for vals in vals_list:
            if not vals.get('company_id'):
                vals['company_id'] = self.env.company.id
            if not vals.get('currency_id'):
                vals['currency_id'] = self.env.company.currency_id.id
            vals.setdefault('date', fields.Datetime.now())
        return super().create(vals_list)

    def write(self, vals):
        raise UserError(self.env._(
            "Approval log entries are immutable and cannot be modified."
        ))

    def unlink(self):
        raise UserError(self.env._(
            "Approval log entries are immutable and cannot be deleted."
        ))

    def copy(self, default=None):
        raise UserError(self.env._(
            "Approval log entries are immutable and cannot be duplicated."
        ))

    def copy_data(self, default=None):
        raise UserError(self.env._(
            "Approval log entries are immutable and cannot be duplicated."
        ))
