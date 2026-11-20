# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html).

import base64
from datetime import timedelta

from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged

from .common import BrokerCommon


@tagged('post_install', '-at_install')
class TestFundingApprovals(BrokerCommon, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env['res.partner'].create({
            'name': 'Approved Client',
            'is_trader': True,
            'risk_level_id': cls.risk_low.id,
        })
        Document = cls.env['broker.kyc.document']
        for document_type in ('passport', 'proof_of_address'):
            Document.create({
                'partner_id': cls.partner.id,
                'document_type': document_type,
                'file': base64.b64encode(b'kyc'),
                'file_name': '%s.pdf' % document_type,
                'expiry_date': cls.today + timedelta(days=700),
                'state': 'approved',
            })
        cls.account = cls.env['broker.trading.account'].create({
            'partner_id': cls.partner.id,
            'account_type': 'live',
            'leverage': '100',
            'state': 'active',
            'risk_level_id': cls.risk_low.id,
        })

    def test_threshold_requires_one_approval_at_the_line_and_two_above_it(self):
        at_threshold = self._create_transaction(self.account, self.risk_low.second_approval_threshold)
        above = self._create_transaction(self.account, self.risk_low.second_approval_threshold + 1)
        self.assertEqual(at_threshold.required_approvals, 1)
        self.assertEqual(above.required_approvals, 2)

    def test_one_approval_is_enough_at_the_threshold(self):
        transaction = self._submit(self.account, self.risk_low.second_approval_threshold)
        self.assertEqual(transaction.required_approvals, 1)
        self.assertEqual(transaction.state, 'to_approve')
        transaction.with_user(self.user_compliance).action_approve()
        self.assertEqual(transaction.state, 'approved')
        self.assertEqual(transaction.approval_count, 1)
        with self.assertRaises(AccessError):
            transaction.with_user(self.user_compliance).action_mark_done()
        transaction.with_user(self.user_finance).action_mark_done()
        self.assertEqual(transaction.state, 'done')
        self.assertEqual(self.account.balance, self.risk_low.second_approval_threshold)
        actions = transaction.approval_log_ids.sorted('id').mapped('action')
        self.assertEqual(actions, ['submit', 'approve', 'done'])

    def test_two_approvals_four_eyes_and_immutable_log(self):
        amount = self.risk_low.second_approval_threshold + 5000
        transaction = self._submit(self.account, amount)
        self.assertEqual(transaction.required_approvals, 2)

        with self.assertRaises(AccessError):
            transaction.with_user(self.user_back_office).action_approve()
        transaction.with_user(self.user_compliance).action_approve()
        self.assertEqual(transaction.state, 'to_approve')
        self.assertEqual(transaction.approval_count, 1)
        with self.assertRaises(AccessError):
            transaction.with_user(self.user_compliance).action_approve()
        self.assertEqual(transaction.approval_count, 1)

        transaction.with_user(self.user_finance).action_approve()
        self.assertEqual(transaction.state, 'approved')
        levels = transaction.approval_log_ids.filtered(lambda entry: entry.action == 'approve').mapped('level')
        self.assertEqual(sorted(levels), [1, 2])

        log = transaction.approval_log_ids[:1]
        with self.assertRaises(UserError):
            log.sudo().write({'comment': 'tampered'})
        with self.assertRaises(UserError):
            log.sudo().unlink()
        with self.assertRaises(UserError):
            log.with_user(self.user_admin).write({'comment': 'tampered'})
        with self.assertRaises(UserError):
            self.env['broker.approval.log'].with_user(self.user_admin).create({
                'res_model': 'broker.transaction',
                'res_id': transaction.id,
                'transaction_id': transaction.id,
                'action': 'approve',
                'user_id': self.user_admin.id,
                'company_id': self.env.company.id,
                'currency_id': self.env.company.currency_id.id,
            })

    def test_requester_cannot_approve_and_the_same_user_cannot_approve_twice(self):
        amount = self.risk_low.second_approval_threshold + 1000
        own_request = self._submit(self.account, amount, user=self.user_compliance)
        with self.assertRaises(UserError):
            own_request.with_user(self.user_compliance).action_approve()
        self.assertEqual(own_request.state, 'to_approve')

        request = self._submit(self.account, amount)
        request.with_user(self.user_finance).action_approve()
        self.assertEqual(request.state, 'to_approve')
        with self.assertRaises(UserError):
            request.with_user(self.user_finance).action_approve()
        self.assertEqual(request.approval_count, 1)
        request.with_user(self.user_finance_2).action_approve()
        self.assertEqual(request.state, 'approved')

    def test_direct_state_change_is_refused_for_staff(self):
        transaction = self._create_transaction(self.account, 100, user=self.user_back_office)
        with self.assertRaises(UserError):
            transaction.write({'state': 'done'})
        with self.assertRaises(UserError):
            self.env['broker.transaction'].with_user(self.user_finance).create({
                'transaction_type': 'deposit',
                'account_id': self.account.id,
                'amount': 100,
                'payment_method': 'card',
                'state': 'done',
            })
