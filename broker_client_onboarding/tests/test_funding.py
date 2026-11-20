# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html).

from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged

from .common import BrokerCommon


@tagged('post_install', '-at_install')
class TestFundingControls(BrokerCommon, TransactionCase):

    def test_live_account_cannot_be_activated_before_kyc(self):
        partner = self._create_trader('Not Ready', self.risk_low)
        self._add_document(partner, 'passport', state='submitted')
        self.assertEqual(partner.kyc_status, 'pending')
        with self.assertRaises(ValidationError):
            self._create_account(partner, state='active')
        draft = self._create_account(partner, state='draft')
        with self.assertRaises(ValidationError):
            draft.action_activate()
        transaction = self._create_transaction(draft, 1000, user=self.user_back_office)
        with self.assertRaises(UserError) as error:
            transaction.action_submit()
        self.assertIn('KYC', str(error.exception))

    def test_live_account_activates_once_kyc_is_approved(self):
        partner = self._create_trader('Ready', self.risk_medium)
        self._approve_kyc(partner)
        account = self._create_account(partner, leverage='100')
        self.assertEqual(account.state, 'active')
        self.assertEqual(account.risk_level_id, self.risk_medium)
        self.assertTrue(account.name.startswith('CFI-'))

    def test_leverage_cannot_exceed_the_risk_cap(self):
        partner = self._create_trader('Restricted', self.risk_high)
        self._approve_kyc(partner)
        with self.assertRaises(ValidationError):
            self._create_account(partner, leverage='100')
        account = self._create_account(partner, leverage='30')
        self.assertEqual(account.leverage, '30')
        with self.assertRaises(ValidationError):
            account.leverage = '50'

    def test_demo_account_rejects_real_money(self):
        partner = self._create_trader('Practice', self.risk_low)
        self._approve_kyc(partner)
        demo = self._create_account(partner, account_type='demo', leverage='500')
        transaction = self._create_transaction(demo, 1000, user=self.user_back_office)
        with self.assertRaises(UserError) as error:
            transaction.action_submit()
        self.assertIn('Demo', str(error.exception))
        self.assertEqual(demo.balance, 0.0)

    def test_single_deposit_withdrawal_and_balance_limits(self):
        partner = self._create_trader('Capped', self.risk_high)
        self._approve_kyc(partner)
        account = self._create_account(partner, leverage='20')
        self._create_transaction(account, 5000, state='done')
        self.assertEqual(account.balance, 5000.0)

        too_large = self._create_transaction(account, self.risk_high.max_single_deposit + 1, user=self.user_back_office)
        with self.assertRaises(UserError) as error:
            too_large.action_submit()
        self.assertIn('single deposit', str(error.exception))

        over_single = self._create_transaction(
            account, self.risk_high.max_single_withdrawal + 1, 'withdrawal', user=self.user_back_office,
        )
        with self.assertRaises(UserError) as error:
            over_single.action_submit()
        self.assertIn('single withdrawal', str(error.exception))

        low_partner = self._create_trader('Thin Balance', self.risk_low)
        self._approve_kyc(low_partner)
        low_account = self._create_account(low_partner)
        self._create_transaction(low_account, 1000, state='done')
        self._submit(low_account, 800, 'withdrawal')
        over_balance = self._create_transaction(low_account, 300, 'withdrawal', user=self.user_back_office)
        with self.assertRaises(UserError) as error:
            over_balance.action_submit()
        self.assertIn('available balance', str(error.exception))

    def test_daily_withdrawal_limit_counts_requests_submitted_today(self):
        partner = self._create_trader('Daily', self.risk_high)
        self._approve_kyc(partner)
        account = self._create_account(partner, leverage='20')
        self._create_transaction(account, 5000, state='done')
        self._create_transaction(account, 5000, state='done')
        self.assertEqual(account.balance, 10000.0)
        self._submit(account, 2000, 'withdrawal')
        second = self._create_transaction(account, 1500, 'withdrawal', user=self.user_back_office)
        with self.assertRaises(UserError) as error:
            second.action_submit()
        self.assertIn('daily withdrawal', str(error.exception))

    def test_account_with_a_balance_cannot_be_closed(self):
        partner = self._create_trader('Still Funded', self.risk_low)
        self._approve_kyc(partner)
        account = self._create_account(partner)
        self._create_transaction(account, 250, state='done')
        with self.assertRaises(UserError):
            account.action_close()
        self._create_transaction(account, 250, 'withdrawal', state='done')
        self.assertEqual(account.balance, 0.0)
        account.action_close()
        self.assertEqual(account.state, 'closed')

    def test_non_trader_cannot_hold_an_account(self):
        partner = self.env['res.partner'].create({'name': 'Just a Contact'})
        with self.assertRaises(ValidationError):
            self.env['broker.trading.account'].create({
                'partner_id': partner.id,
                'account_type': 'demo',
                'leverage': '20',
            })
