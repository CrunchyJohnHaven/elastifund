import os

REPO_ROOT = os.environ.get('ELASTIFUND_REPO', '/Users/johnbradley/Desktop/Elastifund')
VPS_HOST = os.environ.get('VPS_HOST', '34.244.34.108')
VPS_USER = os.environ.get('VPS_USER', 'ubuntu')
VPS_KEY = os.environ.get('VPS_KEY', os.path.expanduser('~/.ssh/lightsail.pem'))
VPS_BOT_PATH = '/home/ubuntu/polymarket-trading-bot'

DATA_DIR = os.path.join(REPO_ROOT, 'data')
STATE_DIR = os.path.join(REPO_ROOT, 'state')
REPORTS_DIR = os.path.join(REPO_ROOT, 'reports')
SCRIPTS_DIR = os.path.join(REPO_ROOT, 'scripts')
