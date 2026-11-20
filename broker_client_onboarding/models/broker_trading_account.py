# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html).

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools.float_utils import float_is_zero

from .const import LEVERAGE_SELECTION, preferred_leverage


class BrokerTradingAccount(models.Model):
    _name = 'broker.trading.account'
    _description = 'Trading Account'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name desc, id desc'

    name = fields.Char(
        string='Account Number',
        required=True,
        copy=False,
        readonly=True,
        default='/',
        tracking=True,
    )
    partner_id = fields.Many2one(
        'res.partner',
        string='Client',
        required=True,
        index=True,
        tracking=True,
        domain=[('is_trader', '=', True)],
    )
    partner_kyc_status = fields.Selection(related='partner_id.kyc_status', string='KYC Status')
    account_type = fields.Selection(
        selection=[('demo', 'Demo'), ('live', 'Live')],
        required=True,
        default='demo',
        tracking=True,
        index=True,
    )
    company_id = fields.Many2one(
        'res.company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    currency_id = fields.Many2one(
        'res.currency',
        required=True,
        default=lambda self: self.env.company.currency_id,
        tracking=True,
    )
    leverage = fields.Selection(selection=LEVERAGE_SELECTION, required=True, default='100', tracking=True)
    risk_level_id = fields.Many2one('broker.risk.level', string='Risk Level', tracking=True, index=True)
    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('active', 'Active'),
            ('suspended', 'Suspended'),
            ('closed', 'Closed'),
        ],
        default='draft',
        required=True,
        tracking=True,
        index=True,
        group_expand=True,
    )
    transaction_ids = fields.One2many('broker.transaction', 'account_id', string='Transactions')
    trade_ids = fields.One2many('broker.trade', 'account_id', string='Trades')
    balance = fields.Monetary(
        compute='_compute_balance',
        store=True,
        currency_field='currency_id',
        compute_sudo=True,
        help="Done deposits minus done withdrawals. Pending requests do not change the balance until Finance marks them done.",
    )
    transaction_count = fields.Integer(compute='_compute_transaction_count')
    notes = fields.Html()

    _name_uniq = models.Constraint(
        'UNIQUE(name)',
        'The account number must be unique.',
    )

    @api.depends('transaction_ids.state', 'transaction_ids.amount', 'transaction_ids.transaction_type')
    def _compute_balance(self):
        totals = {}
        real_ids = [account.id for account in self if isinstance(account.id, int)]
        if real_ids:
            grouped = self.env['broker.transaction']._read_group(
                domain=[('account_id', 'in', real_ids), ('state', '=', 'done')],
                groupby=['account_id', 'transaction_type'],
                aggregates=['amount:sum'],
            )
            for account, tx_type, amount in grouped:
                bucket = totals.setdefault(account.id, {'deposit': 0.0, 'withdrawal': 0.0})
                bucket[tx_type] = amount or 0.0
        for account in self:
            account_id = account.id if isinstance(account.id, int) else None
            data = totals.get(account_id, {})
            account.balance = data.get('deposit', 0.0) - data.get('withdrawal', 0.0)

    def _compute_transaction_count(self):
        for account in self:
            account.transaction_count = len(account.transaction_ids)

    @api.onchange('partner_id')
    def _onchange_partner_id(self):
        if self.partner_id.risk_level_id:
            self.risk_level_id = self.partner_id.risk_level_id
            if not self.leverage or int(self.leverage) > self.risk_level_id.max_leverage:
                self.leverage = preferred_leverage(self.risk_level_id.max_leverage)

    @api.onchange('risk_level_id')
    def _onchange_risk_level_id(self):
        if self.risk_level_id and self.leverage and int(self.leverage) > self.risk_level_id.max_leverage:
            self.leverage = preferred_leverage(self.risk_level_id.max_leverage)
            return {
                'warning': {
                    'title': self.env._("Leverage above the risk cap"),
                    'message': self.env._(
                        "%(risk)s allows at most 1:%(max)s. The leverage on this account was lowered to fit the cap.",
                        risk=self.risk_level_id.name,
                        max=self.risk_level_id.max_leverage,
                    ),
                }
            }

    @api.model_create_multi
    def create(self, vals_list):
        sequence = self.env['ir.sequence'].sudo()
        partners = self.env['res.partner']
        for vals in vals_list:
            if vals.get('name', '/') in (False, '/'):
                vals['name'] = sequence.next_by_code('broker.trading.account') or '/'
            if not vals.get('risk_level_id') and vals.get('partner_id'):
                partner = partners.browse(vals['partner_id'])
                if partner.risk_level_id:
                    vals['risk_level_id'] = partner.risk_level_id.id
            if not vals.get('leverage'):
                max_leverage = 500
                if vals.get('risk_level_id'):
                    max_leverage = self.env['broker.risk.level'].browse(vals['risk_level_id']).max_leverage
                vals['leverage'] = preferred_leverage(max_leverage)
        return super().create(vals_list)

    def copy_data(self, default=None):
        default = dict(default or {})
        vals_list = super().copy_data(default=default)
        for vals in vals_list:
            vals.update({'name': '/', 'state': 'draft'})
        return vals_list

    @api.constrains('partner_id')
    def _check_partner_is_trader(self):
        for account in self:
            if account.partner_id and not account.partner_id.is_trader:
                raise ValidationError(self.env._(
                    "%s is not marked as a trader, so they cannot hold a trading account.",
                    account.partner_id.display_name,
                ))

    @api.constrains('leverage', 'risk_level_id')
    def _check_leverage(self):
        for account in self:
            if not account.risk_level_id or not account.leverage:
                continue
            if int(account.leverage) > account.risk_level_id.max_leverage:
                raise ValidationError(self.env._(
                    "Account %(account)s cannot use 1:%(leverage)s. "
                    "The %(risk)s risk level caps leverage at 1:%(max)s.",
                    account=account.name,
                    leverage=account.leverage,
                    risk=account.risk_level_id.name,
                    max=account.risk_level_id.max_leverage,
                ))

    @api.constrains('state', 'account_type', 'partner_id')
    def _check_live_account_kyc(self):
        for account in self:
            if account.account_type != 'live' or account.state != 'active':
                continue
            if account.partner_id.kyc_status != 'approved':
                status = dict(account.partner_id._fields['kyc_status']._description_selection(self.env)).get(
                    account.partner_id.kyc_status,
                    account.partner_id.kyc_status,
                )
                raise ValidationError(self.env._(
                    "Live account %(account)s cannot be activated: %(client)s has KYC status \"%(status)s\". "
                    "A live account can only be activated when KYC is approved.",
                    account=account.name,
                    client=account.partner_id.display_name,
                    status=status,
                ))

    def action_activate(self):
        for account in self:
            if account.state not in ('draft', 'suspended'):
                raise UserError(self.env._(
                    "Only a draft or suspended account can be activated."
                ))
            account.state = 'active'
        return True

    def action_suspend(self):
        for account in self:
            if account.state != 'active':
                raise UserError(self.env._("Only an active account can be suspended."))
            account.state = 'suspended'
        return True

    def action_close(self):
        for account in self:
            if account.state == 'closed':
                continue
            rounding = account.currency_id.rounding or 0.01
            if not float_is_zero(account.balance, precision_rounding=rounding):
                raise UserError(self.env._(
                    "Account %(account)s still has a balance of %(balance)s %(currency)s. "
                    "Pay the client out before closing the account.",
                    account=account.name,
                    balance=account.balance,
                    currency=account.currency_id.name or '',
                ))
            account.state = 'closed'
        return True

    def action_view_transactions(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Transactions'),
            'res_model': 'broker.transaction',
            'view_mode': 'list,form',
            'domain': [('account_id', '=', self.id)],
            'context': {
                'default_account_id': self.id,
            },
        }
