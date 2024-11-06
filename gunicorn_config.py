bind = "0.0.0.0:10000"
workers = 2
threads = 4
timeout = 120
max_requests = 1000
max_requests_jitter = 50
preload_app = True
worker_class = "sync"
# Consider adding these settings for better logging and error handling
accesslog = "-"  # Log to stdout
errorlog = "-"   # Log errors to stdout
loglevel = "info"