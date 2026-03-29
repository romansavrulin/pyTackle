from EnvDefault import EnvDefault  # noqa: F401
from tackles import TackleFactory  # triggers auto-import of all tackles via __init__.py


def main():
    tackle = TackleFactory.parse_args()
    tackle.do()
