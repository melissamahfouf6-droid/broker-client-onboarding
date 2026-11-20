# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html).

from dateutil.relativedelta import relativedelta

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, tagged

from odoo.addons.broker_client_onboarding.models.const import (
    GROUP_BACK_OFFICE,
    GROUP_COMPLIANCE,
    GROUP_FINANCE,
)

from .common import BrokerCommon


@tagged('post_install', '-at_install')
class TestKycStatus(BrokerCommon, TransactionCase):

    def test_group_implications(self):
        self.assertTrue(self.user_back_office.has_group('base.group_user'))
        self.assertTrue(self.user_back_office.has_group('base.group_partner_manager'))
        self.assertTrue(self.user_compliance.has_group(GROUP_BACK_OFFICE))
        self.assertTrue(self.user_finance.has_group(GROUP_COMPLIANCE))
        self.assertTrue(self.user_admin.has_group(GROUP_FINANCE))

    def test_kyc_not_started_without_documents(self):
        partner = self._create_trader('No File', self.risk_low)
        self.assertEqual(partner.kyc_status, 'not_started')

    def test_kyc_pending_until_both_documents_are_approved(self):
        partner = self._create_trader('Partial File', self.risk_medium)
        self._add_document(partner, 'passport', state='submitted')
        self.assertEqual(partner.kyc_status, 'pending')
        self._add_document(partner, 'passport', state='approved')
        self.assertEqual(partner.kyc_status, 'pending')
        self._add_document(partner, 'proof_of_address', state='approved')
        self.assertEqual(partner.kyc_status, 'approved')

    def test_kyc_rejected_when_nothing_is_left_in_review(self):
        partner = self._create_trader('Refused File', self.risk_high)
        self._add_document(partner, 'national_id', state='rejected', reason='Cropped scan.')
        self.assertEqual(partner.kyc_status, 'rejected')
        self._add_document(partner, 'proof_of_address', state='submitted')
        self.assertEqual(partner.kyc_status, 'pending')

    def test_kyc_valid_on_the_expiry_date_itself(self):
        partner = self._create_trader('Expires Today', self.risk_low)
        self._add_document(partner, 'passport', expiry=self.today)
        self._add_document(partner, 'proof_of_address', expiry=self.today)
        self.assertEqual(partner.kyc_status, 'approved')
        self.env['broker.kyc.document']._cron_expire_documents()
        self.assertEqual(partner.kyc_status, 'approved')
        self.assertTrue(all(document.state == 'approved' for document in partner.kyc_document_ids))

    def test_expiry_recomputes_kyc_and_suspends_the_live_account(self):
        partner = self._create_trader('Lapsed File', self.risk_low)
        self._approve_kyc(partner)
        account = self._create_account(partner)
        self.assertEqual(account.state, 'active')
        proof = partner.kyc_document_ids.filtered(lambda document: document.document_type == 'proof_of_address')
        proof.expiry_date = self.today - relativedelta(days=1)
        self.assertEqual(partner.kyc_status, 'expired')
        self.assertEqual(account.state, 'suspended')
        self.assertEqual(proof.state, 'approved')

        self.env['broker.kyc.document']._cron_expire_documents()
        self.assertEqual(proof.state, 'expired')
        self.assertEqual(partner.kyc_status, 'expired')
        log = self.env['broker.approval.log'].search([
            ('kyc_document_id', '=', proof.id),
            ('action', '=', 'expire'),
        ])
        self.assertEqual(len(log), 1)

        self._add_document(partner, 'proof_of_address', expiry=self.today + relativedelta(days=60))
        self.assertEqual(partner.kyc_status, 'approved')
        self.assertEqual(account.state, 'suspended')
        account.action_activate()
        self.assertEqual(account.state, 'active')

    def test_driving_licence_counts_as_identity(self):
        partner = self._create_trader('Licence Holder', self.risk_medium)
        self._add_document(partner, 'driving_license')
        self._add_document(partner, 'proof_of_address')
        self.assertEqual(partner.kyc_status, 'approved')

    def test_uploader_cannot_approve_or_reject(self):
        partner = self._create_trader('Own Upload', self.risk_low)
        document = self._add_document(partner, 'passport', state='submitted', user=self.user_compliance)
        document.with_user(self.user_finance).action_start_review()
        with self.assertRaises(UserError):
            document.with_user(self.user_compliance).action_approve()
        wizard = self.env['broker.kyc.reject.wizard'].with_user(self.user_compliance).create({
            'document_id': document.id,
            'rejection_reason': 'Trying to reject my own upload.',
        })
        with self.assertRaises(UserError):
            wizard.action_confirm()
        self.assertEqual(document.state, 'under_review')
        document.with_user(self.user_finance).action_approve()
        self.assertEqual(document.state, 'approved')
        self.assertEqual(document.reviewer_id, self.user_finance)

    def test_only_compliance_can_review_and_state_cannot_be_forced(self):
        partner = self._create_trader('Queue', self.risk_low)
        document = self._add_document(partner, 'passport', state='submitted', user=self.user_back_office)
        with self.assertRaises(AccessError):
            document.with_user(self.user_back_office).action_start_review()
        with self.assertRaises(UserError):
            document.with_user(self.user_back_office).write({'state': 'approved'})
        with self.assertRaises(UserError):
            self.env['broker.kyc.document'].with_user(self.user_back_office).create({
                'partner_id': partner.id,
                'document_type': 'proof_of_address',
                'file': self._sample_file(),
                'file_name': 'poa.pdf',
                'state': 'approved',
            })

    def test_rejection_requires_a_reason_and_is_logged(self):
        partner = self._create_trader('Bad Scan', self.risk_high)
        document = self._add_document(partner, 'national_id', state='submitted', user=self.user_back_office)
        document.with_user(self.user_compliance).action_start_review()
        with self.assertRaises(UserError):
            document.with_user(self.user_compliance)._apply_rejection('   ')
        wizard = self.env['broker.kyc.reject.wizard'].with_user(self.user_compliance).create({
            'document_id': document.id,
            'rejection_reason': 'The MRZ is unreadable.',
        })
        wizard.action_confirm()
        self.assertEqual(document.state, 'rejected')
        self.assertEqual(document.rejection_reason, 'The MRZ is unreadable.')
        self.assertEqual(partner.kyc_status, 'rejected')
        log = self.env['broker.approval.log'].search([
            ('kyc_document_id', '=', document.id),
            ('action', '=', 'reject'),
        ])
        self.assertEqual(log.comment, 'The MRZ is unreadable.')
        self.assertEqual(log.user_id, self.user_compliance)
