# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html).

from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged
from odoo.tools.float_utils import float_compare

from .common import BrokerCommon


@tagged('post_install', '-at_install')
class TestIbCommission(BrokerCommon, TransactionCase):

    def _make_ib(self, name, plan):
        return self.env['res.partner'].create({
            'name': name,
            'is_company': True,
            'is_introducing_broker': True,
            'commission_plan_id': plan.id,
        })

    def _funded_client(self, name, risk, ib):
        partner = self._create_trader(name, risk, ib=ib)
        self._approve_kyc(partner)
        account = self._create_account(partner)
        return partner, account

    def _pay_deposit(self, account, amount):
        transaction = self._submit(account, amount)
        transaction.with_user(self.user_compliance).action_approve()
        if transaction.required_approvals == 2:
            transaction.with_user(self.user_finance_2).action_approve()
        transaction.with_user(self.user_finance).action_mark_done()
        return transaction

    def test_percent_of_deposit_and_bulk_settlement(self):
        plan = self.env['broker.commission.plan'].create({
            'name': 'Ten Percent',
            'commission_type': 'percent_of_deposit',
            'rate': 10,
        })
        ib = self._make_ib('North Introducer', plan)
        client, account = self._funded_client('Referred Percent', self.risk_low, ib)
        deposit = self._pay_deposit(account, 2000)
        commission = self.env['broker.ib.commission'].search([('source_transaction_id', '=', deposit.id)])
        self.assertEqual(len(commission), 1)
        self.assertEqual(commission.ib_partner_id, ib)
        self.assertEqual(commission.client_partner_id, client)
        self.assertEqual(commission.base_amount, 2000)
        self.assertEqual(commission.rate, 10)
        self.assertEqual(commission.commission_amount, 200)
        self.assertEqual(commission.state, 'pending')

        withdrawal = self._submit(account, 100, 'withdrawal')
        withdrawal.with_user(self.user_compliance).action_approve()
        withdrawal.with_user(self.user_finance).action_mark_done()
        self.assertFalse(self.env['broker.ib.commission'].search([('source_transaction_id', '=', withdrawal.id)]))

        self.env['broker.trade'].create({
            'account_id': account.id,
            'symbol': 'eurusd',
            'volume_lots': 3,
            'open_datetime': '2026-01-01 10:00:00',
            'close_datetime': '2026-01-01 12:00:00',
        })
        self.assertEqual(self.env['broker.ib.commission'].search_count([('ib_partner_id', '=', ib.id)]), 1)

        with self.assertRaises(AccessError):
            commission.with_user(self.user_back_office).action_confirm()
        commission.with_user(self.user_finance).action_confirm()
        self.assertEqual(commission.state, 'confirmed')
        commission.with_user(self.user_finance).action_mark_paid()
        self.assertEqual(commission.state, 'paid')
        self.assertTrue(float_compare(ib.total_commission, 200, precision_rounding=ib.company_currency_id.rounding) == 0)

    def test_per_lot_on_live_trades_only(self):
        plan = self.env['broker.commission.plan'].create({
            'name': 'Eight a Lot',
            'commission_type': 'per_lot',
            'rate': 8,
        })
        ib = self._make_ib('Volume Desk', plan)
        _client, account = self._funded_client('Referred Volume', self.risk_low, ib)
        trade = self.env['broker.trade'].create({
            'account_id': account.id,
            'symbol': 'xauusd',
            'volume_lots': 2.5,
            'open_datetime': '2026-02-01 08:00:00',
            'close_datetime': '2026-02-01 09:30:00',
        })
        self.assertEqual(trade.symbol, 'XAUUSD')
        commission = trade.commission_ids
        self.assertEqual(len(commission), 1)
        self.assertEqual(commission.base_amount, 2.5)
        self.assertEqual(commission.commission_amount, 20)
        self.assertFalse(commission.source_transaction_id)

        demo = self._create_account(account.partner_id, account_type='demo', leverage='100')
        demo_trade = self.env['broker.trade'].create({
            'account_id': demo.id,
            'symbol': 'EURUSD',
            'volume_lots': 5,
            'open_datetime': '2026-02-02 08:00:00',
        })
        self.assertFalse(demo_trade.commission_ids)

        deposit = self._pay_deposit(account, 1000)
        self.assertFalse(self.env['broker.ib.commission'].search([('source_transaction_id', '=', deposit.id)]))

        second = self.env['broker.trade'].create({
            'account_id': account.id,
            'symbol': 'GBPUSD',
            'volume_lots': 1,
            'open_datetime': '2026-02-03 08:00:00',
            'close_datetime': '2026-02-03 08:30:00',
        })
        book = commission | second.commission_ids
        with self.assertRaises(UserError):
            book.with_user(self.user_finance).action_mark_paid()
        book.with_user(self.user_finance).action_confirm()
        self.assertEqual(set(book.mapped('state')), {'confirmed'})
        book.with_user(self.user_finance).action_mark_paid()
        self.assertEqual(set(book.mapped('state')), {'paid'})
        with self.assertRaises(UserError):
            book.unlink()
