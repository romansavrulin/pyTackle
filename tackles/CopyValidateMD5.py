import pathlib
import re
import unicodedata
import shutil
import os
import logging

from common.FileEntry import FileEntry
from tackles.TackleFactory import TackleFactory

logging.basicConfig(
    level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('root')

# Lenient pattern that accepts both single-space and double-space separators,
# matching the original behaviour of the tackle.
_MD5_LINE_RE = re.compile(r'(?P<md5>\w+)\s(?P<path>.*$)')


def _parse_md5_line(line: str) -> FileEntry | None:
    """Parse an md5sum-style line into a :class:`FileEntry`.

    Accepts both the canonical two-space format produced by ``md5sum`` and the
    single-space variant that some tools emit.  Returns *None* when the line
    does not match.
    """
    m = _MD5_LINE_RE.search(line)
    if m is None:
        return None
    hexdigest = m.group('md5')
    path = unicodedata.normalize('NFC', m.group('path'))
    return FileEntry(path=path, checksum=f'md5:{hexdigest}')


class CopyValidateMD5(TackleFactory):

    @classmethod
    def arg_parser(cls, subparser):
        subparser.add_argument('--to-dir', type=pathlib.Path, required=True)
        subparser.add_argument('--from-dir', type=pathlib.Path, required=True)
        subparser.add_argument('--from-file', type=pathlib.Path, required=True)
        subparser.add_argument('-v', action='store_true', help='verbose output')

    def __init__(self, parser):
        super().__init__(parser)
        options, args = parser.parse_known_args()

        self.to_dir = pathlib.PurePosixPath(unicodedata.normalize('NFC', str(options.to_dir)))
        self.from_dir = pathlib.PurePosixPath(unicodedata.normalize('NFC', str(options.from_dir)))
        self.from_file = pathlib.PurePosixPath(unicodedata.normalize('NFC', str(options.from_file)))

        if options.v:
            logger.setLevel(logging.DEBUG)

        if not os.path.isdir(self.from_dir):
            logger.error(f'From dir {self.from_dir} doesn\'t exists')
            exit(1)

        if not os.path.isdir(self.to_dir):
            logger.error(f'To dir {self.to_dir}  doesn\'t exists')
            exit(2)

        if not os.path.isfile(self.from_file):
            logger.error(f'From file {self.from_file} doesn\'t exists')
            exit(3)

    def do(self):
        with open(self.from_file) as file:
            for line in file:
                entry = _parse_md5_line(line)
                if entry is None:
                    continue

                src_file_rel_path = entry.path
                md5sum = entry.checksum.removeprefix('md5:')
                src_file_rel_dir_name = os.path.dirname(src_file_rel_path)

                src_file = pathlib.PurePosixPath(f'{self.from_dir}/{src_file_rel_path}')
                if not os.path.isfile(src_file):
                    logger.error(f'Source doesn\'t exists: {src_file_rel_path}')
                    continue

                src_entry = FileEntry(path=str(src_file))
                hex_digest = src_entry.calculate_checksum(algorithm='md5')

                if hex_digest != md5sum:
                    logger.error(f'Source checksum ERROR: {md5sum}\t{src_file_rel_path}')
                    continue

                target_subdir = pathlib.PurePosixPath(f'{self.to_dir}/{src_file_rel_dir_name}')
                target_filename = pathlib.PurePosixPath(f'{self.to_dir}/{src_file_rel_path}')

                if not os.path.isdir(target_subdir):
                    logger.debug(f'Creating target subdir "{target_subdir}"')
                    try:
                        os.makedirs(target_subdir, mode=0o777, exist_ok=True)
                    except Exception as e:
                        logger.error(
                            f'Unable to create target subdir {target_subdir} with {e} for: {src_file_rel_path}')
                        continue
                try:
                    shutil.copy2(src_file, target_subdir)
                except Exception as e:
                    logger.error(f'Unable to copy to target with {e} for: {src_file_rel_path}')
                    continue
                logger.debug(f'Target copy OK: {target_filename}')

                target_entry = FileEntry(path=str(target_filename))
                hex_digest = target_entry.calculate_checksum(algorithm='md5')

                if hex_digest != md5sum:
                    logger.error(f'Target checksum ERROR! Removing: {target_filename}')
                    shutil.rmtree(target_filename)
                    continue
                logger.debug(f'Target checksum OK: {target_filename}')
