# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html).

from odoo import fields, models


class BrokerTransactionRejectWizard(models.TransientModel):
    _name = 'broker.transaction.reject.wizard'
    _description = 'Reject Funding Request'

    transaction_id = fields.Many2one('broker.transaction', required=True)
    rejection_reason = fields.Text(
        required=True,
        string='Reason',
        help="Recorded on the immutable approval log. Auditors will read this as the reason the money did not move.",
    )

    def action_confirm(self):
        self.ensure_one()
        self.transaction_id._apply_rejection(self.rejection_reason)
        return {'type': 'ir.actions.act_window_close'}
