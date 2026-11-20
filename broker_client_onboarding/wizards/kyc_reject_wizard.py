# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html).

from odoo import fields, models


class BrokerKycRejectWizard(models.TransientModel):
    _name = 'broker.kyc.reject.wizard'
    _description = 'Reject KYC Document'

    document_id = fields.Many2one('broker.kyc.document', required=True)
    rejection_reason = fields.Text(
        required=True,
        string='Reason',
        help="Shown to the client and stored on the approval log. Say what is wrong with the document, not only that it was refused.",
    )

    def action_confirm(self):
        self.ensure_one()
        self.document_id._apply_rejection(self.rejection_reason)
        return {'type': 'ir.actions.act_window_close'}
