# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html).

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class BrokerTrade(models.Model):
    """A closed or open ticket standing in for a fill synced from MT4/MT5.

    The module does not talk to a trading server. Operations (or a bridge)
    create the ticket here, and a per-lot introducing broker is paid when a
    live-account ticket is booked.
    """

    _name = 'broker.trade'
    _description = 'Trade'
    _order = 'close_datetime desc, open_datetime desc, id desc'

    name = fields.Char(required=True, copy=False, readonly=True, default='/')
    account_id = fields.Many2one('broker.trading.account', required=True, index=True)
    partner_id = fields.Many2one(related='account_id.partner_id', store=True, index=True)
    company_id = fields.Many2one(related='account_id.company_id', store=True, index=True)
    symbol = fields.Char(required=True, index=True, help="MT4/MT5 symbol, for example EURUSD or XAUUSD.")
    volume_lots = fields.Float(required=True, digits=(16, 2), string='Volume (lots)')
    open_datetime = fields.Datetime(required=True)
    close_datetime = fields.Datetime()
    commission_ids = fields.One2many('broker.ib.commission', 'source_trade_id', string='IB Commission')

    _positive_volume = models.Constraint(
        'CHECK(volume_lots > 0)',
        'Trade volume must be greater than zero.',
    )

    @api.onchange('symbol')
    def _onchange_symbol(self):
        if self.symbol:
            self.symbol = self.symbol.strip().upper()

    @api.model_create_multi
    def create(self, vals_list):
        sequence = self.env['ir.sequence'].sudo()
        for vals in vals_list:
            if vals.get('symbol'):
                vals['symbol'] = vals['symbol'].strip().upper()
            if vals.get('name', '/') in (False, '/'):
                vals['name'] = sequence.next_by_code('broker.trade') or '/'
        trades = super().create(vals_list)
        self.env['broker.ib.commission']._generate_from_trade(trades)
        return trades

    @api.constrains('open_datetime', 'close_datetime')
    def _check_times(self):
        for trade in self:
            if trade.close_datetime and trade.open_datetime and trade.close_datetime < trade.open_datetime:
                raise ValidationError(self.env._(
                    "Trade %(trade)s cannot close before it opens.",
                    trade=trade.name,
                ))
