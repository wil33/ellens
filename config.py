import os
from dotenv import load_dotenv

basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, '.env'))

class Config:
    # Basic Flask Config
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-key-never-use-this-in-production'
    FLASK_ENV = os.environ.get('FLASK_ENV', 'production')
    
    # Database Config
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        'sqlite:///' + os.path.join(basedir, 'inventory.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Square API Config
    SQUARE_ACCESS_TOKEN = os.environ.get('SQUARE_ACCESS_TOKEN')
    SQUARE_ENVIRONMENT = os.environ.get('SQUARE_ENVIRONMENT', 'production')

class DevelopmentConfig(Config):
    DEBUG = True
    
class ProductionConfig(Config):
    DEBUG = False

class TestingConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///' + os.path.join(basedir, 'test.db')

config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
}
