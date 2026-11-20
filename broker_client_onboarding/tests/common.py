# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html).

import base64
from datetime import timedelta

from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.tests import new_test_user

from odoo.addons.broker_client_onboarding.models.const import (
    GROUP_ADMINISTRATOR,
    GROUP_BACK_OFFICE,
    GROUP_COMPLIANCE,
    GROUP_FINANCE,
)


class BrokerCommon:
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(
            cls.env.context,
            tracking_disable=True,
            mail_create_nolog=True,
            mail_notrack=True,
            no_reset_password=True,
        ))
        cls.user_back_office = new_test_user(
            cls.env,
            login='broker_back_office',
            groups='base.group_user,%s' % GROUP_BACK_OFFICE,
        )
        cls.user_compliance = new_test_user(
            cls.env,
            login='broker_compliance',
            groups='base.group_user,%s' % GROUP_COMPLIANCE,
        )
        cls.user_finance = new_test_user(
            cls.env,
            login='broker_finance',
            groups='base.group_user,%s' % GROUP_FINANCE,
        )
        cls.user_finance_2 = new_test_user(
            cls.env,
            login='broker_finance_2',
            groups='base.group_user,%s' % GROUP_FINANCE,
        )
        cls.user_admin = new_test_user(
            cls.env,
            login='broker_admin',
            groups='base.group_user,%s' % GROUP_ADMINISTRATOR,
        )
        cls.risk_low = cls.env.ref('broker_client_onboarding.risk_level_low')
        cls.risk_medium = cls.env.ref('broker_client_onboarding.risk_level_medium')
        cls.risk_high = cls.env.ref('broker_client_onboarding.risk_level_high')
        cls.today = fields.Date.context_today(cls.env.user)

    def _sample_file(self):
        return base64.b64encode(b'%PDF-1.4 brokerage kyc sample')

    def _create_trader(self, name, risk, ib=None):
        return self.env['res.partner'].create({
            'name': name,
            'is_trader': True,
            'risk_level_id': risk.id,
            'introducing_broker_id': ib.id if ib else False,
        })

    def _add_document(self, partner, document_type, state='approved', expiry=None, user=None, reason=None):
        vals = {
            'partner_id': partner.id,
            'document_type': document_type,
            'file': self._sample_file(),
            'file_name': '%s.pdf' % document_type,
            'document_number': '%s-%s' % (document_type, partner.id or 'new'),
            'issue_date': self.today - relativedelta(years=1),
            'expiry_date': self.today + relativedelta(years=2) if expiry is None else expiry,
            'state': state,
        }
        if state == 'rejected':
            vals['rejection_reason'] = reason or 'The document is unreadable.'
        documents = self.env['broker.kyc.document']
        if user:
            documents = documents.with_user(user)
        return documents.create(vals)

    def _approve_kyc(self, partner):
        self._add_document(partner, 'passport', expiry=self.today + relativedelta(years=5))
        self._add_document(partner, 'proof_of_address', expiry=self.today + timedelta(days=90))
        return partner

    def _create_account(self, partner, account_type='live', leverage='20', state='active'):
        return self.env['broker.trading.account'].create({
            'partner_id': partner.id,
            'account_type': account_type,
            'leverage': leverage,
            'state': state,
            'risk_level_id': partner.risk_level_id.id,
        })

    def _create_transaction(self, account, amount, transaction_type='deposit', user=None, state=None):
        vals = {
            'transaction_type': transaction_type,
            'account_id': account.id,
            'amount': amount,
            'payment_method': 'bank_transfer',
            'reference': 'TEST-%s' % transaction_type,
        }
        if state:
            vals['state'] = state
        transactions = self.env['broker.transaction']
        if user:
            transactions = transactions.with_user(user)
        return transactions.create(vals)

    def _submit(self, account, amount, transaction_type='deposit', user=None):
        user = user or self.user_back_office
        transaction = self._create_transaction(account, amount, transaction_type, user=user)
        transaction.action_submit()
        return transaction
