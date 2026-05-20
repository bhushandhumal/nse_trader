import os
import time
from dotenv import load_dotenv, set_key
from pyotp import TOTP
from selenium import webdriver
from selenium.webdriver.common.by import By
from kiteconnect import KiteConnect

ENV_FILE = os.path.join(os.path.dirname(__file__), '..', '.env')


def auto_login():
    """Performs headless Selenium login, stores access token in .env."""
    load_dotenv(ENV_FILE)
    api_key = os.environ['APP_KEY']
    api_secret = os.environ['SECRET_KEY']
    username = os.environ['USERNAME']
    password = os.environ['PASSWORD']
    totp = TOTP(os.environ['TOTP'])

    kite = KiteConnect(api_key=api_key)
    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    browser = webdriver.Chrome(options=options)

    browser.get(kite.login_url())
    browser.implicitly_wait(10)

    browser.find_element(By.XPATH, '/html/body/div[1]/div/div[2]/div[1]/div/div/div[2]/form/div[1]/input').send_keys(username)
    browser.find_element(By.XPATH, '/html/body/div[1]/div/div[2]/div[1]/div/div/div[2]/form/div[2]/input').send_keys(password)
    browser.find_element(By.XPATH, '/html/body/div[1]/div/div[2]/div[1]/div/div/div[2]/form/div[4]/button').click()

    browser.find_element(By.XPATH, '/html/body/div[1]/div/div[2]/div[1]/div[2]/div/div[2]/form/div[1]/input').send_keys(totp.now())
    time.sleep(10)

    request_token = browser.current_url.split('request_token=')[1][:32]
    browser.quit()

    data = kite.generate_session(request_token, api_secret=api_secret)
    set_key(ENV_FILE, 'REQUEST_TOKEN', request_token)
    set_key(ENV_FILE, 'ACCESS_TOKEN', data['access_token'])
    print("Login successful. Access token saved.")
    return kite, data['access_token']


def load_session():
    """Loads api_key and access_token from .env and returns a ready KiteConnect instance."""
    load_dotenv(ENV_FILE)
    api_key = os.environ['APP_KEY']
    access_token = os.environ['ACCESS_TOKEN']
    kite = KiteConnect(api_key=api_key)
    kite.set_access_token(access_token)
    return kite
