# Tagbandhu

**A QR-Based Safety and Identification Platform**

Tagbandhu is a web application designed to help people identify and reconnect with the owners of registered tags for children, elderly individuals, and personal belongings.

## Features

- User registration and login
- QR-based tag identification
- Tag activation and management
- Child safety and elderly assistance use cases
- Bag and luggage identification
- Contact form for communicating with a tag owner
- OTP verification for contact requests
- Email notifications
- Admin inventory and activity history

## Tech Stack

- **Backend:** Python, Flask
- **Database:** SQLite / SQLAlchemy
- **Frontend:** HTML, CSS, Jinja2
- **QR Codes:** Python QR code library
- **Database Migrations:** Flask-Migrate / Alembic

## Local Setup

1. Clone the repository:

   ```bash
   git clone https://github.com/Shazia63khan/Tagbandhu.git
   cd Tagbandhu
   ```

2. Create and activate a virtual environment:

   ```bash
   python -m venv .venv
   ```

   Windows PowerShell:

   ```powershell
   .\.venv\Scripts\Activate.ps1
   ```

3. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

4. Configure the required environment variables in a local `.env` file. Never commit passwords, secret keys, or other credentials.

5. Run the application using the startup command configured in `app.py`.

## Security and Privacy

Tagbandhu is a developing project. Security, privacy, and usability improvements are ongoing. Do not use real personal or sensitive data during development.

## Project Status

Under development as a final-year academic project.

## Author

Shazia Bano

GitHub: [Shazia63khan](https://github.com/Shazia63khan)
