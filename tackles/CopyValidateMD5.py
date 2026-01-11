import pathlib
import re
import unicodedata
import shutil
import os
import hashlib
import logging

from tackles.TackleFactory import TackleFactory

logging.basicConfig(
    level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('root')


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
                for m in re.finditer('(?P<md5>\\w+)\\s(?P<path>.*$)', line):

                    src_file_rel_path = unicodedata.normalize('NFC', m.group("path"))
                    md5sum = m.group('md5')
                    src_file_rel_dir_name = os.path.dirname(src_file_rel_path)

                    src_file = pathlib.PurePosixPath(f'{self.from_dir}/{src_file_rel_path}')
                    if not os.path.isfile(src_file):
                        logger.error(f'Source doesn\'t exists: {src_file_rel_path}')
                        continue

                    with open(src_file, "rb") as f:
                        file_hash = hashlib.md5()
                        while chunk := f.read(8192):
                            file_hash.update(chunk)

                    hex_digest = file_hash.hexdigest()

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

                    with open(target_filename, "rb") as f:
                        file_hash = hashlib.md5()
                        while chunk := f.read(8192):
                            file_hash.update(chunk)

                    hex_digest = file_hash.hexdigest()

                    if hex_digest != md5sum:
                        logger.error(f'Target checksum ERROR! Removing: {target_filename}')
                        shutil.rmtree(target_filename)
                        continue
                    logger.debug(f'Target checksum OK: {target_filename}')
