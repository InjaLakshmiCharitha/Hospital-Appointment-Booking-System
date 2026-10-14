# Hospital Appointment Booking System

# Project Overview

The Hospital Appointment Booking System is a backend application developed using FastAPI and MySQL. It enables patients to book and manage appointments with doctors, allows doctors to manage schedules and consultations, and provides administrators with management and reporting functionality.

The system supports JWT authentication, role-based access control, appointment scheduling, doctor leaves, appointment status tracking, medical file uploads, real-time queue updates using WebSockets, email notifications, automated background jobs, reports, and appointment ratings.

# Technologies Used

- Python 3.9+
- FastAPI
- MySQL
- SQLAlchemy
- Alembic
- Pydantic
- JWT authentication
- Passlib and bcrypt
- WebSockets
- APScheduler
- SMTP using aiosmtplib
- Uvicorn
- Pytest
- HTTPX
- ReportLab 

# Main Features

# Authentication and Authorization
- Patient registration and login
- JWT access and refresh tokens
- Token refresh and logout
- Password hashing
- Role-based authorization for Admin, Doctor, and Patient
- Authenticated user profile retrieval
- Authorized administrator creation of doctor accounts

# Department and Doctor Management
- Department management
- Doctor management
- Doctor search and filtering
- Doctor schedules and working hours
- Doctor leave management
- Available appointment slots

# Appointment Management
- Appointment booking
- Appointment rescheduling and cancellation
- Patient check-in
- No-show processing
- Appointment status history
- Appointment tokens and appointment fee snapshots

# Consultations and Files
- Consultation records
- Symptoms, diagnosis, prescriptions, and advice
- Follow-up information
- Medical file uploads and downloads
- Supported file types and size restrictions enforced by the upload endpoint

# Live Queue and Notifications
- Live queue updates using WebSockets
- Personalized queue information
- Doctor's Call Next Patient functionality
- Patient and doctor notifications
- Estimated waiting time

# Background Jobs and Emails
- Appointment reminder processing
- Automatic no-show processing
- Follow-up email processing
- SMTP email delivery
- WebSocket notifications

# Reports and Ratings
- Administrative reports
- Doctor performance reporting
- Department summaries
- Appointment ratings and feedback, if enabled in the implementation

# Project Structure

Hospital Appointment Booking System/
├── app/
│   ├── auth/
│   ├── jobs/
│   │   ├── appointment_reminders.py
│   │   ├── no_show_job.py
│   │   ├── follow_up_emails.py
│   │   └── scheduler.py
│   ├── models/
│   │   └── models.py
│   ├── routers/
│   │   ├── auth.py
│   │   ├── departments.py
│   │   ├── doctors.py
│   │   ├── schedules.py
│   │   ├── leaves.py
│   │   ├── appointments.py
│   │   ├── consultations.py
│   │   ├── files.py
│   │   ├── patient.py
│   │   ├── queue.py
│   │   ├── notifications.py
│   │   ├── reports.py
│   │   └── ratings.py
│   ├── schemas/
│   ├── services/
│   │   ├── email_service.py
│   │   └── notification_service.py
│   ├── websockets/
│   │   └── manager.py
│   ├── database.py
│   └── main.py
├── alembic/
│   └── versions/
├── static/
│   └── queue_test.html
├── uploads/
├── .env.example
├── .gitignore
├── alembic.ini
├── requirements.txt
└── README.md


# Installation and Setup

# Create a Virtual Environment

- python -m venv venv

- Activate the virtual environment on Windows Command Prompt:
venv\Scripts\activate


# Install Dependencies

- python -m pip install --upgrade pip

- pip install -r requirements.txt

- If a dependency is missing, add the required package to 'requirements.txt' and install it. Do not install unrelated packages unnecessarily.

# Create the MySQL Database

- Open MySQL Workbench or the MySQL command line and run:
CREATE DATABASE hospital_appointment_db;

- Use the same database name in your environment configuration.

# Configure Environment Variables

- Create a '.env' file in the project root by copying '.env.example'.

- Update the values in '.env' according to your MySQL and SMTP configuration.

- Example configuration:

DATABASE_URL=mysql+pymysql://root:YOUR_MYSQL_PASSWORD@localhost:3306/hospital_appointment_db

SECRET_KEY=replace_with_a_long_random_secret
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=7

INITIAL_ADMIN_SETUP_KEY=replace_with_a_long_random_setup_key

SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your_email@gmail.com
SMTP_PASSWORD=your_gmail_app_password
SMTP_FROM=your_email@gmail.com


- The names of environment variables must match those read by the application. The email service in this project reads 'SMTP_HOST', 'SMTP_PORT', 'SMTP_USER', 'SMTP_PASSWORD', and 'SMTP_FROM'.

- Never commit the '.env' file or real credentials to GitHub. Keep '.env.example' populated only with placeholder values.

# Database Migrations with Alembic

- Alembic is used to manage database schema changes.

- Run the following commands from the project root after activating the virtual environment.

# Check Migration Status
- alembic current

# View Migration History
- alembic history

# Apply Existing Migrations
- alembic upgrade head

# Generate a New Migration
- After changing SQLAlchemy models, generate a migration:
alembic revision --autogenerate -m "describe the schema change"

- Review the generated migration before applying it:
alembic upgrade head

- Do not generate a new initial migration if one already exists. Confirm that the existing migrations can create the database schema correctly.

- For a clean development setup, test the migrations against an empty development database before submission. Do not delete or reset a database containing important data.

# Running the Application

- From the project root, start the FastAPI application:
uvicorn app.main:app --reload

When the server starts successfully, open:
- API root: http://127.0.0.1:8000/
- Swagger UI: http://127.0.0.1:8000/docs
- ReDoc: http://127.0.0.1:8000/redoc
- Queue test page: http://127.0.0.1:8000/queue-test

The queue test page works only if 'static/queue_test.html' exists and its JavaScript uses the correct WebSocket endpoints.

# User Roles and Test Credentials

The system uses three main roles.

| Role    | Permissions                                                                                        |
|---      |-------                                                                                             |
| Admin   | Manage authorized administrative operations, create doctor accounts, and access authorized reports |
| Doctor  | Manage their own schedule, handle consultations, and call the next patient                         |
| Patient | Register, log in, book appointments, and manage their own appointments                             |

# Patient Account

- Register a patient through the public registration endpoint documented in Swagger:
POST /auth/register

- Log in using the registered credentials:
POST /auth/login

# Admin Account

- Use the protected initial administrator setup flow implemented in the authentication router, if enabled. Configure the setup key in '.env' before using it.
- After the initial administrator is created, use the authorized admin functionality to create doctor accounts.

# Doctor Account
- Create a doctor account using the authorized administrator functionality provided by the application. Then log in using the created doctor's credentials.

# Test Credentials Table

Fill in the actual credentials you create in your local development environment.

| Role    | Test email                           | Test password                         |
|---      |------                                |------                                 |
| Admin   | Replace with your test admin email   | Replace with your local test password |
| Doctor  | Replace with your test doctor email  | Replace with your local test password |
| Patient | Replace with your test patient email | Replace with your local test password |

Use dummy test accounts only. Never publish production credentials or real user passwords in the repository. If the evaluation requires credentials, use dedicated development accounts and follow your mentor's submission instructions.

# Authentication and Swagger Testing

Open:

http://127.0.0.1:8000/docs

Recommended testing sequence:

1. Register a patient.
2. Log in and copy the returned access token.
3. Click **Authorize** in Swagger.
4. Enter the token in the format requested by the authentication scheme.
5. Call the current-user endpoint.
6. Configure the administrator account through the authorized setup process, if needed.
7. Create a department and doctor.
8. Create the doctor's schedule.
9. Test leave management and available slots.
10. Book an appointment as a patient.
11. Test rescheduling, cancellation, and check-in.
12. Test consultations and file uploads.
13. Test the live queue and notifications.
14. Test reports and ratings.


# WebSocket Testing

The application includes WebSocket endpoints for queue updates and personal notifications.

# Live Queue WebSocket
- ws://127.0.0.1:8000/ws/queue/{doctor_id}?token=ACCESS_TOKEN

# Personal Notifications WebSocket
- ws://127.0.0.1:8000/ws/notifications?token=ACCESS_TOKEN
- Replace '{doctor_id}' with an existing doctor's ID and ACCESS_TOKEN' with a valid access token.

# Testing Procedure
1. Start the FastAPI server.
2. Log in as a patient or doctor and obtain an access token.
3. Open '/queue-test' if the HTML page supports queue connections.
4. Connect to the doctor's queue WebSocket.
5. Connect another authorized client to the same doctor's queue.
6. Check in a patient.
7. Log in as the doctor and call the next patient.
8. Verify that the queue updates reach the connected clients.
9. Connect to the personal notification WebSocket.
10. Trigger an action that sends a notification and verify the received message.

Capture screenshots showing the connected clients and live queue updates.

The current connection manager stores WebSocket connections in application memory. It is suitable for a single application process; a multi-worker deployment requires shared messaging infrastructure.

# SMTP Email Setup

The application sends emails through SMTP using aiosmtplib.

For Gmail:
1. Enable two-step verification on the Gmail account.
2. Generate a Gmail App Password if available for the account.
3. Configure the SMTP host as 'smtp.gmail.com'.
4. Use port '587' with STARTTLS.
5. Add the sender email, SMTP username, and App Password to '.env'.
6. Restart the application after changing environment variables.

Example:
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your_email@gmail.com
SMTP_PASSWORD=your_gmail_app_password
SMTP_FROM=your_email@gmail.com


# Email Testing

Test the email functionality and capture the actual received messages for:
- Appointment booking confirmation
- Appointment reminder
- Appointment cancellation

Check the spam folder and application logs if a message is not received. A successful API response does not necessarily prove that an email reached the inbox.

# Automated Background Jobs

The scheduler is started by the FastAPI application lifespan.

| Job                   | Schedule         | Purpose                                               |
|---                    |---               |---                                                    |
| Appointment reminders | Every hour       | Checks eligible upcoming appointments                 |
| No-show processing    | Every 15 minutes | Processes appointments meeting the no-show conditions |
| Follow-up emails      | Daily at 9:00 AM | Processes eligible follow-up emails                   |

The configured schedule uses the scheduler's configured timezone. Confirm that it matches the intended local time.

The appointment reminder job checks the approximately 23–24-hour window before an appointment. The no-show job checks appointments that meet its configured cutoff.

Review application logs and actual database records to confirm that the jobs work correctly. Email delivery also depends on SMTP credentials and network connectivity.

# File Uploads and Medical Documents

The project includes a file upload router and a local uploads directory.

Use the file upload endpoint documented in Swagger. Verify the implemented restrictions for file type, file size, and authorization.

Test that authorized users can download the correct files and unauthorized users cannot access private medical documents.

Do not commit uploaded medical documents or patient information to GitHub.

# Running Automated Tests

- If the project includes a test suite, activate the virtual environment and run:
pytest

- To show more detailed output:
pytest -v

- Run tests from the project root so that Python can import the 'app' package. Configure a separate test database when tests interact with MySQL.


# Conclusion

The Hospital Appointment Booking System demonstrates backend development using FastAPI, MySQL, SQLAlchemy, Alembic, JWT authentication, role-based access control, appointment management, WebSockets, background processing, and SMTP email notifications.
The project is ready for submission after the documented setup steps, migrations, API endpoints, WebSocket behavior, and email delivery have been tested and the required screenshots have been captured.

