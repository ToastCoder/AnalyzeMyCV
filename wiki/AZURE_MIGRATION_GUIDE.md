# Email Authentication and Azure SQL

The application uses email/password authentication. User records are stored in
Azure SQL and passwords are stored only as bcrypt hashes.

## Required environment variables

```env
AZURE_SQL_DATABASE_URL=mssql+pyodbc://username:password@server.database.windows.net/analyzemycv?driver=ODBC+Driver+17+for+SQL+Server
JWT_SECRET=at-least-32-random-characters
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_API_KEY=your-key
AZURE_OPENAI_DEPLOYMENT_NAME=gpt-5-mini
API_URL=http://localhost:8080
```

Use Azure App Service Configuration for production secrets. Do not commit
`.env` or place passwords in source code.

## Local setup

1. Install dependencies from `requirements.txt`.
2. Install Microsoft's ODBC Driver for SQL Server.
3. Copy `.env.example` to `.env` and fill in the values.
4. Start the API and Streamlit client with `./entrypoint.sh`.

Tables are initialized at API startup. On an older database, startup adds
`users.password_hash` and makes the old `entra_id` column nullable. Existing
Entra users do not have a password hash and must create a new account or be
migrated separately.

## Authentication API

`POST /auth/signup` and `POST /auth/login` accept:

```json
{"email": "user@example.com", "password": "at-least-8-characters"}
```

They return a JWT in `access_token`. Send it to protected endpoints using:

```text
Authorization: Bearer <access_token>
```

`POST /auth/verify` validates a token and `POST /auth/logout` clears the
client-side session.

## Security

- Passwords require at least eight characters and are hashed with bcrypt.
- `JWT_SECRET` must be long, random, and identical across app instances.
- Use HTTPS in production and restrict Azure SQL firewall rules.
