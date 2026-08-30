# Security

- Keep `.env` out of source control; production secrets belong in Azure App
  Service Configuration or Azure Key Vault.
- Store only bcrypt password hashes in Azure SQL. Never log or return a
  password.
- Set `JWT_SECRET` to a random value of at least 32 characters and keep it
  consistent across app instances.
- Use HTTPS in production and restrict Azure SQL firewall access.
- Set `CORS_ORIGINS` to only the client origins that need API access.
- Send JWTs in the `Authorization: Bearer` header, not in URLs.
- Rotate Azure OpenAI, database, and JWT secrets if they are exposed.
- Review Git history before publishing and use a secret scanner in CI.
