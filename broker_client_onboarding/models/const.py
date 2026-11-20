# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html).

from odoo.exceptions import AccessError

GROUP_BACK_OFFICE = 'broker_client_onboarding.group_broker_back_office'
GROUP_COMPLIANCE = 'broker_client_onboarding.group_broker_compliance'
GROUP_FINANCE = 'broker_client_onboarding.group_broker_finance'
GROUP_ADMINISTRATOR = 'broker_client_onboarding.group_broker_administrator'

IDENTITY_DOCUMENT_TYPES = ('passport', 'national_id', 'driving_license')
ADDRESS_DOCUMENT_TYPE = 'proof_of_address'

# Steps a CFD broker actually offers. The string is the client-facing ratio;
# the key is the numeric leverage stored for the risk-level comparison.
LEVERAGE_SELECTION = [
    ('1', '1:1'),
    ('2', '1:2'),
    ('5', '1:5'),
    ('10', '1:10'),
    ('20', '1:20'),
    ('30', '1:30'),
    ('50', '1:50'),
    ('100', '1:100'),
    ('200', '1:200'),
    ('300', '1:300'),
    ('400', '1:400'),
    ('500', '1:500'),
]

# Requests that already consume the daily withdrawal allowance.
DAILY_LIMIT_STATES = ('to_approve', 'approved', 'done')
# Requests that still hold funds which the ledger has not yet paid out.
RESERVED_WITHDRAWAL_STATES = ('to_approve', 'approved')


def ensure_group(env, group_xmlid, message):
    """Raise AccessError unless the current user is in ``group_xmlid``."""
    if not env.user.has_group(group_xmlid):
        raise AccessError(message)


def preferred_leverage(max_leverage):
    """Default a new account to 1:100, or the highest step the risk cap allows."""
    allowed = [int(key) for key, _label in LEVERAGE_SELECTION if int(key) <= (max_leverage or 0)]
    if not allowed:
        return '1'
    retail_cap = [value for value in allowed if value <= 100]
    return str(max(retail_cap or allowed))
