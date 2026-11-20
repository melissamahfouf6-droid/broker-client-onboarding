# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html).

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_compare

from .const import (
    DAILY_LIMIT_STATES,
    GROUP_COMPLIANCE,
    GROUP_FINANCE,
    RESERVED_WITHDRAWAL_STATES,
    ensure_group,
)


class BrokerTransaction(models.Model):
    _name = 'broker.transaction'
    _description = 'Deposit or Withdrawal'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(required=True, copy=False, readonly=True, default='/', tracking=True)
    transaction_type = fields.Selection(
        selection=[('deposit', 'Deposit'), ('withdrawal', 'Withdrawal')],
        required=True,
        tracking=True,
        index=True,
    )
    account_id = fields.Many2one(
        'broker.trading.account',
        string='Trading Account',
        required=True,
        index=True,
        tracking=True,
    )
    partner_id = fields.Many2one(
        'res.partner',
        string='Client',
        related='account_id.partner_id',
        store=True,
        index=True,
    )
    partner_kyc_status = fields.Selection(related='partner_id.kyc_status', string='KYC Status')
    company_id = fields.Many2one(related='account_id.company_id', store=True, index=True)
    currency_id = fields.Many2one(related='account_id.currency_id', store=True)
    risk_level_id = fields.Many2one(related='account_id.risk_level_id', store=True)
    limit_currency_id = fields.Many2one(related='risk_level_id.currency_id')
    amount = fields.Monetary(required=True, currency_field='currency_id', tracking=True)
    max_single_deposit = fields.Monetary(related='risk_level_id.max_single_deposit', currency_field='limit_currency_id')
    max_single_withdrawal = fields.Monetary(related='risk_level_id.max_single_withdrawal', currency_field='limit_currency_id')
    daily_withdrawal_limit = fields.Monetary(related='risk_level_id.daily_withdrawal_limit', currency_field='limit_currency_id')
    second_approval_threshold = fields.Monetary(
        related='risk_level_id.second_approval_threshold',
        currency_field='limit_currency_id',
    )
    available_to_withdraw = fields.Monetary(
        compute='_compute_available_to_withdraw',
        currency_field='currency_id',
        help="Account balance minus other withdrawals that are approved or waiting for approval.",
    )
    payment_method = fields.Selection(
        selection=[
            ('bank_transfer', 'Bank Transfer'),
            ('card', 'Card'),
            ('e_wallet', 'E-Wallet'),
            ('crypto', 'Crypto'),
        ],
        required=True,
        default='bank_transfer',
        tracking=True,
    )
    reference = fields.Char(help="Bank reference, card authorisation or transaction hash supplied by the client.")
    requested_by = fields.Many2one(
        'res.users',
        string='Requested By',
        required=True,
        default=lambda self: self.env.user,
        tracking=True,
        copy=False,
    )
    submitted_date = fields.Date(readonly=True, copy=False, tracking=True)
    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('to_approve', 'To Approve'),
            ('approved', 'Approved'),
            ('done', 'Done'),
            ('rejected', 'Rejected'),
            ('cancelled', 'Cancelled'),
        ],
        default='draft',
        required=True,
        tracking=True,
        index=True,
        group_expand=True,
    )
    required_approvals = fields.Integer(
        compute='_compute_required_approvals',
        store=True,
        help="1, or 2 when the amount is above the risk level's second-approval threshold.",
    )
    approval_count = fields.Integer(compute='_compute_approval_count', store=True)
    approval_log_ids = fields.One2many('broker.approval.log', 'transaction_id', string='Approval Log')

    _name_uniq = models.Constraint(
        'UNIQUE(name)',
        'The transaction reference must be unique.',
    )
    _positive_amount = models.Constraint(
        'CHECK(amount > 0)',
        'The amount must be positive.',
    )

    @api.depends(
        'amount',
        'currency_id',
        'submitted_date',
        'risk_level_id.second_approval_threshold',
        'risk_level_id.currency_id',
        'company_id',
    )
    def _compute_required_approvals(self):
        for tx in self:
            risk = tx.risk_level_id
            if not risk or not tx.currency_id or not risk.currency_id:
                tx.required_approvals = 1
                continue
            amount = tx._amount_in_limit_currency(tx.amount)
            rounding = risk.currency_id.rounding or 0.01
            if float_compare(amount, risk.second_approval_threshold, precision_rounding=rounding) > 0:
                tx.required_approvals = 2
            else:
                tx.required_approvals = 1

    @api.depends('approval_log_ids.action')
    def _compute_approval_count(self):
        for tx in self:
            tx.approval_count = len(tx.approval_log_ids.filtered(lambda entry: entry.action == 'approve'))

    @api.depends(
        'account_id.balance',
        'account_id.transaction_ids.state',
        'account_id.transaction_ids.amount',
        'account_id.transaction_ids.transaction_type',
        'state',
    )
    def _compute_available_to_withdraw(self):
        for tx in self:
            if not tx.account_id:
                tx.available_to_withdraw = 0.0
                continue
            tx.available_to_withdraw = tx.account_id.balance - tx._reserved_withdrawal_amount()

    def _amount_in_limit_currency(self, amount):
        self.ensure_one()
        risk = self.risk_level_id
        company = self.company_id or self.env.company
        date = self.submitted_date or fields.Date.context_today(self)
        return self.currency_id._convert(amount, risk.currency_id, company, date)

    def _reserved_withdrawal_amount(self):
        """Funds already spoken for by other withdrawals that have not been paid."""
        self.ensure_one()
        if not self.account_id:
            return 0.0
        domain = [
            ('account_id', '=', self.account_id.id),
            ('transaction_type', '=', 'withdrawal'),
            ('state', 'in', RESERVED_WITHDRAWAL_STATES),
        ]
        if isinstance(self.id, int):
            domain.append(('id', '!=', self.id))
        return sum(self.search(domain).mapped('amount'))

    def _approval_count_db(self):
        self.ensure_one()
        self.env.flush_all()
        return self.env['broker.approval.log'].sudo().search_count([
            ('transaction_id', '=', self.id),
            ('action', '=', 'approve'),
        ])

    def _log(self, action, level=0, comment=False):
        for tx in self:
            self.env['broker.approval.log'].log_decision(tx, action, level=level, comment=comment)
        self.invalidate_recordset(['approval_log_ids', 'approval_count'])

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su:
            for vals in vals_list:
                if vals.get('state') not in (None, False, 'draft'):
                    raise UserError(self.env._(
                        "A funding request starts as a draft. Submit it for approval."
                    ))
        sequence = self.env['ir.sequence'].sudo()
        for vals in vals_list:
            if vals.get('name', '/') in (False, '/'):
                code = (
                    'broker.transaction.deposit'
                    if vals.get('transaction_type') == 'deposit'
                    else 'broker.transaction.withdrawal'
                )
                vals['name'] = sequence.next_by_code(code) or '/'
        records = super().create(vals_list)
        records.filtered(lambda tx: tx.state == 'done' and tx.transaction_type == 'deposit')._accrue_ib_commission()
        return records

    def write(self, vals):
        if 'state' in vals and not self.env.su and not self.env.context.get('broker_state_change'):
            raise UserError(self.env._(
                "Move a funding request through Submit, Approve and Mark as Done. The status cannot be edited directly."
            ))
        protected = {'amount', 'transaction_type', 'account_id', 'payment_method', 'currency_id'}
        if protected & set(vals):
            locked = self.filtered(lambda tx: tx.state not in ('draft', 'rejected', 'cancelled'))
            if locked:
                raise UserError(self.env._(
                    "Amount, account and payment method are locked once the request has been submitted. "
                    "Cancel it and raise a new one if the instruction changed."
                ))
        return super().write(vals)

    def copy_data(self, default=None):
        default = dict(default or {})
        vals_list = super().copy_data(default=default)
        for vals in vals_list:
            vals.update({
                'name': '/',
                'state': 'draft',
                'submitted_date': False,
                'requested_by': self.env.user.id,
            })
        return vals_list

    def unlink(self):
        for tx in self:
            if tx.state not in ('draft', 'cancelled') or tx.approval_log_ids:
                raise UserError(self.env._(
                    "A funding request that has been submitted stays on the audit file and cannot be deleted."
                ))
        return super().unlink()

    def _check_funding_rules(self):
        """Regulatory and risk checks shared by submit and by marking the payment done."""
        self.ensure_one()
        self.env.flush_all()
        account = self.account_id
        risk = account.risk_level_id
        if account.account_type != 'live':
            raise UserError(self.env._(
                "Demo accounts cannot accept real deposits or withdrawals. Open a live account once KYC is approved."
            ))
        if account.partner_id.kyc_status != 'approved':
            raise UserError(self.env._(
                "Funding is blocked: %(client)s does not have approved KYC. "
                "Compliance must approve a current identity document and a current proof of address first.",
                client=account.partner_id.display_name,
            ))
        if account.state != 'active':
            raise UserError(self.env._(
                "Account %(account)s is %(state)s. Only an active live account can be funded or withdrawn.",
                account=account.name,
                state=dict(account._fields['state']._description_selection(self.env)).get(account.state, account.state),
            ))
        if not risk:
            raise UserError(self.env._(
                "Account %(account)s has no risk level, so funding limits cannot be applied.",
                account=account.name,
            ))
        rounding = (risk.currency_id.rounding or self.currency_id.rounding or 0.01)
        amount = self._amount_in_limit_currency(self.amount)
        if self.transaction_type == 'deposit':
            if float_compare(amount, risk.max_single_deposit, precision_rounding=rounding) > 0:
                raise UserError(self.env._(
                    "This deposit of %(amount)s exceeds the single deposit limit of %(limit)s on the %(risk)s risk level.",
                    amount=amount,
                    limit=risk.max_single_deposit,
                    risk=risk.name,
                ))
            return
        if float_compare(amount, risk.max_single_withdrawal, precision_rounding=rounding) > 0:
            raise UserError(self.env._(
                "This withdrawal of %(amount)s exceeds the single withdrawal limit of %(limit)s on the %(risk)s risk level.",
                amount=amount,
                limit=risk.max_single_withdrawal,
                risk=risk.name,
            ))
        available = account.balance - self._reserved_withdrawal_amount()
        account_rounding = account.currency_id.rounding or 0.01
        if float_compare(self.amount, available, precision_rounding=account_rounding) > 0:
            raise UserError(self.env._(
                "Withdrawal of %(amount)s exceeds the available balance of %(available)s on %(account)s. "
                "Pending withdrawals are already reserved.",
                amount=self.amount,
                available=available,
                account=account.name,
            ))
        today = fields.Date.context_today(self)
        day = self.submitted_date or today
        others = self.search([
            ('account_id', '=', account.id),
            ('transaction_type', '=', 'withdrawal'),
            ('state', 'in', DAILY_LIMIT_STATES),
            ('submitted_date', '=', day),
            ('id', '!=', self.id),
        ])
        total = sum(others.mapped('amount')) + self.amount
        total_limit = self._amount_in_limit_currency(total)
        if float_compare(total_limit, risk.daily_withdrawal_limit, precision_rounding=rounding) > 0:
            raise UserError(self.env._(
                "This withdrawal would take today's requests on %(account)s to %(total)s, above the daily withdrawal limit of %(limit)s.",
                account=account.name,
                total=total_limit,
                limit=risk.daily_withdrawal_limit,
            ))

    def action_submit(self):
        self = self.with_context(broker_state_change=True)
        for tx in self:
            if tx.state != 'draft':
                raise UserError(self.env._("Only a draft request can be submitted."))
            tx.write({
                'submitted_date': fields.Date.context_today(tx),
                'requested_by': self.env.user.id,
            })
            tx._check_funding_rules()
            tx.state = 'to_approve'
            tx._log('submit')
            tx.message_post(
                body=self.env._(
                    "%(kind)s of %(amount)s submitted by %(user)s. Approvals required: %(count)s.",
                    kind=dict(tx._fields['transaction_type']._description_selection(self.env)).get(tx.transaction_type),
                    amount=tx.amount,
                    user=self.env.user.display_name,
                    count=tx.required_approvals,
                ),
                subtype_xmlid='mail.mt_note',
            )
        return True

    def _check_can_decide(self):
        self.ensure_one()
        if self.state != 'to_approve':
            raise UserError(self.env._("Only a request waiting for approval can be approved or rejected."))
        if self.requested_by == self.env.user:
            raise UserError(self.env._(
                "Four-eyes rule: you cannot approve or reject a request you submitted."
            ))
        self.env.flush_all()
        already = self.env['broker.approval.log'].sudo().search_count([
            ('transaction_id', '=', self.id),
            ('action', '=', 'approve'),
            ('user_id', '=', self.env.user.id),
        ])
        if already:
            raise UserError(self.env._(
                "Four-eyes rule: you have already approved this request. A different person must give the next approval."
            ))

    def _check_level_group(self, level):
        if level == 1:
            ensure_group(self.env, GROUP_COMPLIANCE, self.env._(
                "Level 1 approval is restricted to Compliance Officers."
            ))
        elif level == 2:
            ensure_group(self.env, GROUP_FINANCE, self.env._(
                "Level 2 approval is restricted to Finance Managers."
            ))
        else:
            raise UserError(self.env._("This request does not accept more than two approvals."))

    def action_approve(self):
        self = self.with_context(broker_state_change=True)
        for tx in self:
            level = tx._approval_count_db() + 1
            tx._check_level_group(level)
            tx._check_can_decide()
            tx._log('approve', level=level)
            if tx._approval_count_db() >= tx.required_approvals:
                tx.state = 'approved'
                body = self.env._(
                    "Approved at level %(level)s by %(user)s. The request now has every required approval.",
                    level=level,
                    user=self.env.user.display_name,
                )
            else:
                body = self.env._(
                    "Level %(level)s approval recorded by %(user)s. A Finance Manager still has to approve.",
                    level=level,
                    user=self.env.user.display_name,
                )
            tx.message_post(body=body, subtype_xmlid='mail.mt_note')
        return True

    def action_reject(self):
        self.ensure_one()
        level = self._approval_count_db() + 1
        self._check_level_group(level)
        self._check_can_decide()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Reject Funding Request'),
            'res_model': 'broker.transaction.reject.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_transaction_id': self.id},
        }

    def _apply_rejection(self, reason):
        self = self.with_context(broker_state_change=True)
        reason = (reason or '').strip()
        if not reason:
            raise UserError(self.env._("A rejection reason is required so the audit log records why the money did not move."))
        for tx in self:
            level = tx._approval_count_db() + 1
            tx._check_level_group(level)
            tx._check_can_decide()
            tx.state = 'rejected'
            tx._log('reject', level=level, comment=reason)
            tx.message_post(
                body=self.env._("Rejected by %(user)s. %(reason)s", user=self.env.user.display_name, reason=reason),
                subtype_xmlid='mail.mt_note',
            )
        return True

    def action_mark_done(self):
        self = self.with_context(broker_state_change=True)
        ensure_group(self.env, GROUP_FINANCE, self.env._(
            "Only a Finance Manager can mark a funding request as done."
        ))
        for tx in self:
            if tx.state != 'approved':
                raise UserError(self.env._(
                    "Mark a request done only after it has every required approval."
                ))
            if tx._approval_count_db() < tx.required_approvals:
                raise UserError(self.env._(
                    "%(request)s has %(have)s of the %(need)s required approvals.",
                    request=tx.name,
                    have=tx._approval_count_db(),
                    need=tx.required_approvals,
                ))
            tx._check_funding_rules()
            tx.state = 'done'
            tx._log('done')
            tx._accrue_ib_commission()
            tx.message_post(
                body=self.env._("Marked done by %s. The account balance now includes this movement.", self.env.user.display_name),
                subtype_xmlid='mail.mt_note',
            )
        return True

    def _accrue_ib_commission(self):
        self.env['broker.ib.commission']._generate_from_deposit(self)

    def action_cancel(self):
        self = self.with_context(broker_state_change=True)
        for tx in self:
            if tx.state not in ('draft', 'to_approve', 'approved'):
                raise UserError(self.env._(
                    "A request that is already done, rejected or cancelled cannot be cancelled. Raise a reversing transaction instead."
                ))
            if tx.state == 'approved' and not self.env.user.has_group(GROUP_FINANCE):
                raise UserError(self.env._(
                    "Only a Finance Manager can cancel a request that already has every approval."
                ))
            tx.state = 'cancelled'
            tx._log('cancel')
            tx.message_post(
                body=self.env._("Cancelled by %s.", self.env.user.display_name),
                subtype_xmlid='mail.mt_note',
            )
        return True

    def action_reset_to_draft(self):
        self = self.with_context(broker_state_change=True)
        for tx in self:
            if tx.state not in ('rejected', 'cancelled'):
                raise UserError(self.env._(
                    "Only a rejected or cancelled request can be reset to draft."
                ))
            tx.write({'state': 'draft', 'submitted_date': False})
            tx.message_post(
                body=self.env._("Reset to draft by %s.", self.env.user.display_name),
                subtype_xmlid='mail.mt_note',
            )
        return True
