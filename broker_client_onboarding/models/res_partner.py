# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html).

from odoo import api, fields, models
from odoo.exceptions import ValidationError

from .const import ADDRESS_DOCUMENT_TYPE, IDENTITY_DOCUMENT_TYPES


class ResPartner(models.Model):
    _inherit = 'res.partner'

    is_trader = fields.Boolean(string='Trader', tracking=True, help="A client who holds demo or live trading accounts.")
    is_introducing_broker = fields.Boolean(
        string='Is an Introducing Broker',
        tracking=True,
        help="A partner who refers clients and is paid commission on their deposits or volume.",
    )
    risk_level_id = fields.Many2one(
        'broker.risk.level',
        string='Risk Level',
        tracking=True,
        help="Drives the leverage cap and the funding limits copied onto new trading accounts.",
    )
    trading_account_ids = fields.One2many('broker.trading.account', 'partner_id', string='Trading Accounts')
    kyc_document_ids = fields.One2many('broker.kyc.document', 'partner_id', string='KYC Documents')
    transaction_ids = fields.One2many('broker.transaction', 'partner_id', string='Transactions')
    kyc_status = fields.Selection(
        selection=[
            ('not_started', 'Not Started'),
            ('pending', 'Pending'),
            ('approved', 'Approved'),
            ('rejected', 'Rejected'),
            ('expired', 'Expired'),
        ],
        string='KYC Status',
        compute='_compute_kyc_status',
        store=True,
        tracking=True,
        index=True,
        help="Approved only when a current identity document and a current proof of address are both approved.",
    )
    introducing_broker_id = fields.Many2one(
        'res.partner',
        string='Introducing Broker',
        domain="[('is_introducing_broker', '=', True), ('id', '!=', id)]",
        tracking=True,
        index=True,
    )
    ib_client_ids = fields.One2many('res.partner', 'introducing_broker_id', string='Referred Clients')
    commission_plan_id = fields.Many2one('broker.commission.plan', string='Commission Plan', tracking=True)
    commission_ids = fields.One2many('broker.ib.commission', 'ib_partner_id', string='Commissions')
    company_currency_id = fields.Many2one('res.currency', compute='_compute_company_currency_id', store=True)
    total_commission = fields.Monetary(
        string='Total Commission',
        compute='_compute_total_commission',
        store=True,
        currency_field='company_currency_id',
        help="Introducing-broker commission in company currency, including pending, confirmed and paid.",
    )
    trading_account_count = fields.Integer(compute='_compute_broker_counts')
    kyc_document_count = fields.Integer(compute='_compute_broker_counts')
    transaction_count = fields.Integer(compute='_compute_broker_counts')
    commission_count = fields.Integer(compute='_compute_broker_counts')
    ib_client_count = fields.Integer(compute='_compute_broker_counts')

    @api.depends('company_id')
    def _compute_company_currency_id(self):
        fallback = self.env.company.currency_id
        for partner in self:
            partner.company_currency_id = partner.company_id.currency_id or fallback

    @api.depends(
        'kyc_document_ids.state',
        'kyc_document_ids.document_type',
        'kyc_document_ids.expiry_date',
    )
    def _compute_kyc_status(self):
        today = fields.Date.context_today(self)
        for partner in self:
            partner.kyc_status = partner._kyc_status_from_documents(partner.kyc_document_ids, today)

    @api.model
    def _kyc_status_from_documents(self, documents, today):
        """Regulatory KYC outcome for one client file.

        Approved requires one in-date identity document (passport, national ID
        or driving licence) and one in-date proof of address, both approved.
        A file that is being reviewed stays pending even if an older document
        was rejected or has expired. Expiry wins over rejection once nothing
        is left in the queue, because the client used to be approved.
        """
        def valid(document):
            return (
                document.state == 'approved'
                and (not document.expiry_date or document.expiry_date >= today)
            )

        if any(valid(document) and document.document_type in IDENTITY_DOCUMENT_TYPES for document in documents) \
                and any(valid(document) and document.document_type == ADDRESS_DOCUMENT_TYPE for document in documents):
            return 'approved'
        if any(document.state in ('submitted', 'under_review') for document in documents):
            return 'pending'
        if any(
            document.state == 'expired'
            or (document.state == 'approved' and document.expiry_date and document.expiry_date < today)
            for document in documents
        ):
            return 'expired'
        if any(document.state == 'rejected' for document in documents):
            return 'rejected'
        if documents:
            return 'pending'
        return 'not_started'

    @api.depends(
        'commission_ids.commission_amount',
        'commission_ids.currency_id',
        'commission_ids.state',
        'company_currency_id',
        'company_id',
    )
    def _compute_total_commission(self):
        today = fields.Date.context_today(self)
        for partner in self:
            company = partner.company_id or self.env.company
            target = partner.company_currency_id or company.currency_id
            total = 0.0
            for commission in partner.commission_ids:
                if not commission.currency_id or not target:
                    continue
                total += commission.currency_id._convert(
                    commission.commission_amount,
                    target,
                    company,
                    today,
                )
            partner.total_commission = target.round(total) if target else total

    def _compute_broker_counts(self):
        for partner in self:
            partner.trading_account_count = len(partner.trading_account_ids)
            partner.kyc_document_count = len(partner.kyc_document_ids)
            partner.transaction_count = len(partner.transaction_ids)
            partner.commission_count = len(partner.commission_ids)
            partner.ib_client_count = len(partner.ib_client_ids)

    @api.onchange('introducing_broker_id')
    def _onchange_introducing_broker_id(self):
        if self.introducing_broker_id:
            self.is_trader = True

    @api.constrains('introducing_broker_id', 'is_introducing_broker')
    def _check_introducing_broker(self):
        for partner in self:
            ib = partner.introducing_broker_id
            if ib and ib == partner:
                raise ValidationError(self.env._("A client cannot be their own introducing broker."))
            if ib and not ib.is_introducing_broker:
                raise ValidationError(self.env._(
                    "%s is not marked as an introducing broker.",
                    ib.display_name,
                ))
            if not partner.is_introducing_broker and partner.ib_client_ids:
                raise ValidationError(self.env._(
                    "%s still has referred clients. Move them to another introducing broker before clearing the flag.",
                    partner.display_name,
                ))

    def _broker_window(self, model, domain, context, name):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': name,
            'res_model': model,
            'view_mode': 'list,form',
            'domain': domain,
            'context': context,
        }

    def action_view_trading_accounts(self):
        self.ensure_one()
        return self._broker_window(
            'broker.trading.account',
            [('partner_id', '=', self.id)],
            {'default_partner_id': self.id},
            self.env._('Trading Accounts'),
        )

    def action_view_kyc_documents(self):
        self.ensure_one()
        return self._broker_window(
            'broker.kyc.document',
            [('partner_id', '=', self.id)],
            {'default_partner_id': self.id},
            self.env._('KYC Documents'),
        )

    def action_view_transactions(self):
        self.ensure_one()
        return self._broker_window(
            'broker.transaction',
            [('partner_id', '=', self.id)],
            {'default_partner_id': self.id},
            self.env._('Deposits & Withdrawals'),
        )

    def action_view_commissions(self):
        self.ensure_one()
        return self._broker_window(
            'broker.ib.commission',
            [('ib_partner_id', '=', self.id)],
            {'default_ib_partner_id': self.id},
            self.env._('IB Commissions'),
        )

    def action_view_referred_clients(self):
        self.ensure_one()
        return self._broker_window(
            'res.partner',
            [('introducing_broker_id', '=', self.id)],
            {'default_introducing_broker_id': self.id, 'default_is_trader': True},
            self.env._('Referred Clients'),
        )
