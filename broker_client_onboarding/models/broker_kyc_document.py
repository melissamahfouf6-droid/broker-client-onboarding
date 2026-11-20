# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html).

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

from .const import GROUP_COMPLIANCE, ensure_group


class BrokerKycDocument(models.Model):
    _name = 'broker.kyc.document'
    _description = 'KYC Document'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(compute='_compute_name', store=True)
    partner_id = fields.Many2one('res.partner', string='Client', required=True, index=True, tracking=True)
    document_type = fields.Selection(
        selection=[
            ('passport', 'Passport'),
            ('national_id', 'National ID'),
            ('driving_license', 'Driving Licence'),
            ('proof_of_address', 'Proof of Address'),
        ],
        required=True,
        tracking=True,
        index=True,
    )
    file = fields.Binary(string='File', attachment=True, required=True)
    file_name = fields.Char(string='Filename')
    document_number = fields.Char(tracking=True)
    issue_date = fields.Date()
    expiry_date = fields.Date(
        tracking=True,
        help="Leave empty only when the document truly does not expire. The daily job moves an approved document to Expired the day after this date.",
    )
    state = fields.Selection(
        selection=[
            ('submitted', 'Submitted'),
            ('under_review', 'Under Review'),
            ('approved', 'Approved'),
            ('rejected', 'Rejected'),
            ('expired', 'Expired'),
        ],
        default='submitted',
        required=True,
        tracking=True,
        index=True,
        group_expand=True,
    )
    reviewer_id = fields.Many2one('res.users', string='Reviewer', readonly=True, tracking=True, copy=False)
    review_date = fields.Datetime(readonly=True, copy=False)
    rejection_reason = fields.Text(readonly=True, copy=False)
    approval_log_ids = fields.One2many('broker.approval.log', 'kyc_document_id', string='Approval Log')
    company_id = fields.Many2one(
        'res.company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    is_uploader = fields.Boolean(compute='_compute_is_uploader')

    @api.depends('partner_id.name', 'document_type', 'document_number')
    def _compute_name(self):
        for document in self:
            label = dict(document._fields['document_type']._description_selection(document.env)).get(document.document_type, '')
            parts = [document.partner_id.name, label, document.document_number]
            document.name = ' · '.join(part for part in parts if part)

    def _compute_is_uploader(self):
        user = self.env.user
        for document in self:
            document.is_uploader = bool(document.create_uid) and document.create_uid == user

    @api.constrains('issue_date', 'expiry_date')
    def _check_dates(self):
        for document in self:
            if document.issue_date and document.expiry_date and document.expiry_date < document.issue_date:
                raise ValidationError(self.env._(
                    "The expiry date of %(document)s cannot be earlier than the issue date.",
                    document=document.display_name,
                ))

    @api.constrains('state', 'rejection_reason')
    def _check_rejection_reason(self):
        for document in self:
            if document.state == 'rejected' and not (document.rejection_reason or '').strip():
                raise ValidationError(self.env._(
                    "A rejection reason is required. The client must be told why the document was refused."
                ))

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su:
            for vals in vals_list:
                if vals.get('state') not in (None, False, 'submitted'):
                    raise UserError(self.env._(
                        "Upload the document as submitted. A compliance officer reviews it from there."
                    ))
        documents = super().create(vals_list)
        documents._suspend_unapproved_live_accounts()
        return documents

    def write(self, vals):
        if 'state' in vals and not self.env.su and not self.env.context.get('broker_state_change'):
            raise UserError(self.env._(
                "Change a KYC document through the review buttons. The status cannot be edited directly."
            ))
        partners = self.mapped('partner_id')
        res = super().write(vals)
        if {'state', 'expiry_date', 'document_type', 'partner_id'} & set(vals):
            self._suspend_partners(partners | self.mapped('partner_id'))
        return res

    def unlink(self):
        for document in self:
            if document.state != 'submitted' or document.approval_log_ids:
                raise UserError(self.env._(
                    "A KYC document that has entered review stays on the client file and cannot be deleted."
                ))
        return super().unlink()

    def _suspend_unapproved_live_accounts(self):
        self._suspend_partners(self.mapped('partner_id'))

    def _suspend_partners(self, partners):
        """Stop live trading money movement as soon as KYC is no longer approved.

        Reactivation is deliberate: a fresh approval does not turn the account
        back on by itself.
        """
        for partner in partners:
            if partner.kyc_status == 'approved':
                continue
            accounts = partner.trading_account_ids.filtered(
                lambda account: account.account_type == 'live' and account.state == 'active'
            )
            if not accounts:
                continue
            accounts.write({'state': 'suspended'})
            status = dict(partner._fields['kyc_status']._description_selection(self.env)).get(
                partner.kyc_status,
                partner.kyc_status,
            )
            for account in accounts:
                account.message_post(
                    body=self.env._(
                        "Live account suspended. %(client)s is \"%(status)s\" for KYC, so funding stays blocked until compliance approves a current identity document and a current proof of address.",
                        client=partner.display_name,
                        status=status,
                    ),
                    subtype_xmlid='mail.mt_note',
                )

    def _check_compliance_officer(self):
        ensure_group(self.env, GROUP_COMPLIANCE, self.env._(
            "Only a Compliance Officer can review KYC documents."
        ))

    def _check_not_uploader(self):
        self.ensure_one()
        if self.create_uid == self.env.user:
            raise UserError(self.env._(
                "You cannot approve or reject %(document)s because you uploaded it. Another compliance officer has to make the decision.",
                document=self.display_name,
            ))

    def _log(self, action, comment=False):
        for document in self:
            self.env['broker.approval.log'].log_decision(document, action, comment=comment)

    def action_start_review(self):
        self = self.with_context(broker_state_change=True)
        self._check_compliance_officer()
        for document in self:
            if document.state != 'submitted':
                raise UserError(self.env._(
                    "Only a submitted document can be moved into review."
                ))
            document.write({'state': 'under_review'})
            document._log('review')
            document.message_post(
                body=self.env._("Review started by %s.", self.env.user.display_name),
                subtype_xmlid='mail.mt_note',
            )
        return True

    def action_approve(self):
        self = self.with_context(broker_state_change=True)
        self._check_compliance_officer()
        for document in self:
            if document.state != 'under_review':
                raise UserError(self.env._(
                    "Approve a document only after review has started."
                ))
            document._check_not_uploader()
            document.write({
                'state': 'approved',
                'reviewer_id': self.env.user.id,
                'review_date': fields.Datetime.now(),
                'rejection_reason': False,
            })
            document._log('approve')
            document.message_post(
                body=self.env._("Approved by %s.", self.env.user.display_name),
                subtype_xmlid='mail.mt_note',
            )
        return True

    def action_reject(self):
        self._check_compliance_officer()
        self.ensure_one()
        if self.state != 'under_review':
            raise UserError(self.env._(
                "Reject a document only while it is under review."
            ))
        self._check_not_uploader()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Reject KYC Document'),
            'res_model': 'broker.kyc.reject.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_document_id': self.id},
        }

    def _apply_rejection(self, reason):
        """Called by the rejection wizard once a reason has been captured."""
        self = self.with_context(broker_state_change=True)
        self._check_compliance_officer()
        reason = (reason or '').strip()
        if not reason:
            raise UserError(self.env._(
                "A rejection reason is required. The client must be told why the document was refused."
            ))
        for document in self:
            if document.state != 'under_review':
                raise UserError(self.env._(
                    "Reject a document only while it is under review."
                ))
            document._check_not_uploader()
            document.write({
                'state': 'rejected',
                'reviewer_id': self.env.user.id,
                'review_date': fields.Datetime.now(),
                'rejection_reason': reason,
            })
            document._log('reject', comment=reason)
            document.message_post(
                body=self.env._("Rejected by %(user)s. %(reason)s", user=self.env.user.display_name, reason=reason),
                subtype_xmlid='mail.mt_note',
            )
        return True

    def action_reset_to_submitted(self):
        self = self.with_context(broker_state_change=True)
        for document in self:
            if document.state == 'submitted':
                continue
            if document.state in ('under_review', 'approved') and not self.env.user.has_group(GROUP_COMPLIANCE):
                raise UserError(self.env._(
                    "Only a Compliance Officer can return a document that is already in review or approved."
                ))
            document.write({
                'state': 'submitted',
                'reviewer_id': False,
                'review_date': False,
                'rejection_reason': False,
            })
            document._log('submit', comment=self.env._("Reset to submitted."))
            document.message_post(
                body=self.env._("Returned to submitted by %s.", self.env.user.display_name),
                subtype_xmlid='mail.mt_note',
            )
        return True

    @api.model
    def _cron_expire_documents(self):
        """Daily job: an approved document is expired the day after its expiry date.

        Expiring the document recomputes the client's KYC status and suspends
        live accounts that no longer have a valid file.
        """
        today = fields.Date.context_today(self)
        documents = self.search([
            ('state', '=', 'approved'),
            ('expiry_date', '!=', False),
            ('expiry_date', '<', today),
        ])
        for document in documents:
            document.write({'state': 'expired'})
            self.env['broker.approval.log'].log_decision(
                document,
                'expire',
                comment=self.env._("Marked expired by the daily check because the expiry date has passed."),
            )
            document.message_post(
                body=self.env._(
                    "Expired on %(date)s. The document was valid through %(expiry)s.",
                    date=today,
                    expiry=document.expiry_date,
                ),
                subtype_xmlid='mail.mt_note',
            )
        return True
