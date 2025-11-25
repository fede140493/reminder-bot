versioni minime (python 3.7.3, python-telegram-bot==13.15, apscheduler==3.10.4, python-dotenv==1.0.1, pytz==2024.1)
il bot gira su raspberry pi 3b.

cd /home/pi/reminder
git init
echo -e ".env\n.venv/\n__pycache__/\nreminders.json\n*.pyc" > .gitignore
git add main.py .gitignore README.md   # se hai il README
git commit -m "Add Telegram reminder bot"
git remote add origin https://github.com/tuoutente/tuorepo.git
git push -u origin master   # o main
