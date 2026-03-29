import os

from dotenv import load_dotenv
from tackles.TackleFactory import TackleFactory
from bs4 import BeautifulSoup
import urllib.parse
import requests
import logging

load_dotenv()

logging.basicConfig(
    level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('root')

class GetCoursera(TackleFactory):
    BASE_HEADERS = {
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Sec-Fetch-Site': 'same-origin',
        'Sec-Fetch-Dest': 'document',
        'Accept-Language': 'ru',
        'Sec-Fetch-Mode': 'navigate',
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.3.1 Safari/605.1.15',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Priority': 'u=0, i'
    }

    @classmethod
    def arg_parser(cls, subparser):
        subparser.add_argument(
            '--url',
            type=str,
            default='https://school.getcourse.ru',
            help='Base URL of the GetCourse site (default: https://school.getcourse.ru)',
        )

    def __init__(self, parser):
        super().__init__(parser)
        options, _ = parser.parse_known_args()

        self.base = options.url.rstrip('/')
        self.headers = {
            **self.BASE_HEADERS,
            'Cookie': os.environ['GETCOURSE_COOKIE'],
            'Referer': f'{self.base}/sales/control/userProduct/my',
        }

        trainings = self.get_trainings(f'{self.base}/teach/control/stream', self.headers)
        for training in trainings:
            print(f"Training Name: {training['name']}")
            print(f"Training URL: {training['url']}")
            print(f'Training Description: {training["description"]}')
            blocks = self.get_lessons(training['url'], self.headers)
            for block in blocks:
                print(f"  Lesson Name: {block['name']}")
                print(f"  Lesson URL: {block['url']}")
                modules = self.get_modules(block['url'], self.headers)
                for module in modules:
                    print(f"    Module Name: {module['name']}")
                    print(f"    Module URL: {module['url']}")

    def base_url(self, url, with_path=False):
        parsed = urllib.parse.urlparse(url)
        path = '/'.join(parsed.path.split('/')[:-1]) if with_path else ''
        parsed = parsed._replace(path=path)
        parsed = parsed._replace(params='')
        parsed = parsed._replace(query='')
        parsed = parsed._replace(fragment='')
        return parsed.geturl()

    def convert_url(self, url):
        parts = url.split('/')
        if parts[3] == 'teach':
            parts.insert(3, 'pl')  # Insert 'pl' after 'teach'
            parts.remove('id')
            parts[-1] = f"?id={parts[-1]}&editMode=0"  # Modify the last part to include query parameters
        return '/'.join(parts)

    def get_trainings(self, home_url, headers):
        response = requests.get(home_url, headers=headers)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            trainings = []
            for row in soup.find_all('tr'):
                container = row.find('a')
                if container:
                    name = container.find('span').text
                    url = self.base_url(home_url) + container['href']
                    descr = " ".join(container.find('div').text.split())
                    trainings.append({'name': name, 'url': url, 'description': descr})
            return trainings
        else:
            print(f"Failed to retrieve courses: {response.status_code}")
            return []

    def get_lessons(self, course_url, headers):
        print(f'Getting lessons from {course_url}')
        response = requests.get(course_url, headers=headers)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            blocks = []
            #print(f'Getting lessons from {course_url}')
            for container in soup.find_all("div", {'class':['link', 'title']}):
                name = container.find(text=True, recursive=False).text.strip()
                url = self.convert_url(self.base_url(course_url.rsplit('/', 1)[0]) + container['href'])
                blocks.append({'name': name, 'url': url})
            return blocks
        else:
            print(f"Failed to retrieve blocks: {response.status_code}")
            return []

    #lesson
    def get_modules(self, block_url, headers):
        print(f'Getting modules from {block_url}')
        response = requests.get(block_url, headers=headers)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            blocks = []
            for link in soup.find_all("div", {'class':['header', 'f-header', 'f-lesson-header-1']}):
                block_name = link.find(text=True).text.strip()
                if link.has_key('href'):
                    block_url = self.base_url(block_url.rsplit('/', 1)[0]) + link['href']
                else:
                    block_url = None
                block_content = link.decode_contents()
                blocks.append({
                    'name': block_name,
                    'url': block_url,
                    'content': block_content
                })
                print(block_content)
            return blocks
        else:
            print(f"Failed to retrieve modules: {response.status_code}")
            return []