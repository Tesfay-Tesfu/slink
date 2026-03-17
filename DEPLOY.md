# 🚀 Deploying SOLI MICROLINK to Render.com

## Prerequisites
- GitHub account
- Render.com account
- Gmail account with App Password (for emails)
- Stripe account (for payments)

## Step 1: Prepare Your Repository

1. Push all code to a GitHub repository
2. Make sure you have these files:
   - `backend/app.py` (main application)
   - `backend/requirements.txt` (dependencies)
   - `Procfile` (gunicorn command)
   - `render.yaml` (Render configuration)
   - All frontend templates in `frontend/templates/`

## Step 2: Create a PostgreSQL Database on Render

1. Log into [Render Dashboard](https://dashboard.render.com)
2. Click "New +" → "PostgreSQL"
3. Name: `soli-microlink-db`
4. Database: `solimicrolink`
5. User: `solimicrolink_user`
6. Choose a plan (Free tier works for testing)
7. Click "Create Database"
8. Once created, copy the "Internal Database URL" (starts with `postgres://`)

## Step 3: Create a Web Service on Render

1. Click "New +" → "Web Service"
2. Connect your GitHub repository
3. Configure:
   - **Name**: `soli-microlink`
   - **Environment**: Python 3
   - **Build Command**: `pip install -r backend/requirements.txt`
   - **Start Command**: `gunicorn backend.app:app`
   - **Plan**: Free

## Step 4: Set Environment Variables

In your Web Service dashboard, go to "Environment" and add:

| Key | Value |
|-----|-------|
| `DATABASE_URL` | (paste the Internal Database URL from Step 2) |
| `SECRET_KEY` | (generate a random string) |
| `MAIL_USERNAME` | tesfaymn402@gmail.com |
| `MAIL_PASSWORD` | (your Gmail App Password - NO SPACES) |
| `STRIPE_PUBLIC_KEY` | pk_test_... |
| `STRIPE_SECRET_KEY` | sk_test_... |
| `ADMIN_EMAIL` | tesfaymn402@gmail.com |

## Step 5: Deploy!

1. Click "Manual Deploy" → "Deploy latest commit"
2. Wait for the build to complete (5-10 minutes)
3. Once done, click the URL to view your live site!

## Important Notes

### Gmail App Password
To get an App Password:
1. Enable 2-Factor Authentication on your Gmail
2. Go to Security → App Passwords
3. Generate a password for "Mail"
4. Use that password in `MAIL_PASSWORD` (remove any spaces)

### First Login
- Admin login: username `admin`, password `Admin123!`
- **IMPORTANT**: Change this password immediately after first login!

### Troubleshooting

If you get errors:
1. Check the "Logs" tab in Render dashboard
2. Verify all environment variables are set correctly
3. Make sure the database URL starts with `postgresql://` (not `postgres://`)

## Your App is Live! 🎉

Once deployed, your app will be available at:
`https://soli-microlink.onrender.com`
