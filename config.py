from dotenv import load_dotenv
import os

load_dotenv()

# Основные пути
BOT_TOKEN = os.getenv("BOT_TOKEN")
HOMEWORK_FILE = "data/Домашка.xlsx"
HOMEWORK_TIMESTAMP = "data/timestamp.txt"

# Папки
os.makedirs("data", exist_ok=True)
os.makedirs("data/backup", exist_ok=True)

def get_admins():
    if not os.path.exists('admins.txt'):
        return []
    with open('admins.txt', 'r') as f:
        return [int(line.strip()) for line in f if line.strip().isdigit()]
