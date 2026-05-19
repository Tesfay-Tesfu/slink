# Deploying SOLI MICROLINK to Render.com

## Prerequisites
- GitHub account
- Render.com account
- Your code pushed to a GitHub repository

## Step 1: Prepare your repository
1. Push your code to GitHub
2. Make sure you have these files:
   - `backend/app.py` (PostgreSQL version)
   - `backend/requirements.txt` (with psycopg2-binary and gunicorn)
   - `render.yaml` (for infrastructure as code)

## Step 2: Create a PostgreSQL database on Render
1. Go to [render.com](https://render.com) and login
2. Click "New +" and select "PostgreSQL"
3. Name it `soli-microlink-db`
4. Choose a plan (Free tier works for testing)
5. Click "Create Database"
6. Wait for it to be created
7. Copy the "Internal Database URL" - you'll need it

## Step 3: Migrate your data
Run the migration script locally:
```bash
cd ~/Documents/Soli_Website_Final/backend
export DATABASE_URL="postgresql://your-render-database-url"
python migrate_to_postgres.py
