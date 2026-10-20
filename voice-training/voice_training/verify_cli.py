import sys
from .common import setup_platform
setup_platform()
from .verify import main
main(sys.argv[1])
