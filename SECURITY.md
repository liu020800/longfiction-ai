# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 1.0.x   | :white_check_mark: |
| < 1.0   | :x:                |

## Reporting a Vulnerability

If you discover a security vulnerability, please follow these steps:

### 1. **Do NOT** open a public issue

Security vulnerabilities should NOT be disclosed publicly until they are fixed.

### 2. Email the maintainer

Send a detailed report to the project maintainer via GitHub private messaging or email.

### 3. Include in your report

- **Description** of the vulnerability
- **Steps to reproduce**
- **Potential impact**
- **Suggested fix** (if you have one)
- **Your name/handle** (for credit in the security advisory)

### 4. Response time

- We will acknowledge receipt within **48 hours**
- We will provide a detailed response within **7 days**
- We will work on a fix and coordinate disclosure timing with you

## Security Best Practices

When deploying LongFiction-AI, please follow these security guidelines:

### Environment Variables

**NEVER** commit `.env` files to version control.

The `.gitignore` file already excludes `.env` files. Always use `.env.example` as a template.

```bash
# Good
cp .env.example .env
# Edit .env with your actual values

# Bad
echo "OPENAI_API_KEY=sk-real-key" > .env
git add .env
git commit -m "add config"
```

### API Keys

- Use strong, unique API keys
- Rotate keys regularly
- Set usage limits in your LLM provider's dashboard
- Monitor usage for unusual activity

### Database Security

- Use strong database passwords
- Restrict database network access
- Enable SSL/TLS for database connections
- Regular backups stored securely

### Web Application

- Use HTTPS in production
- Configure CORS appropriately
- Implement rate limiting
- Keep dependencies updated

### JWT Authentication

The application uses JWT for authentication. Ensure:

- Use a strong `JWT_SECRET_KEY` (at least 32 random characters)
- Set appropriate token expiration
- Refresh tokens regularly
- Store tokens securely on the client

### Network Security

- Use a firewall to restrict access
- Deploy behind a reverse proxy (Nginx, Caddy)
- Enable rate limiting
- Monitor logs for suspicious activity

## Known Security Considerations

### Current Implementation

1. **CORS**: Currently allows all origins (`*`) - should be restricted in production
2. **JWT Secret**: No default secret is set, but ensure you configure one
3. **Admin Password**: Default `admin123456` - **MUST be changed** in production
4. **Database**: SQLite is fine for development, use PostgreSQL in production

### Security Roadmap

- [ ] Add rate limiting middleware
- [ ] Implement CORS configuration via env vars
- [ ] Add security headers (HSTS, CSP, X-Frame-Options)
- [ ] Add request validation
- [ ] Add audit logging
- [ ] Implement 2FA for admin accounts

## Disclosure Policy

When we receive a security report:

1. We will investigate and confirm the vulnerability
2. We will develop a fix
3. We will release a security patch
4. We will publish a security advisory (CVE if applicable)
5. We will credit the reporter (if desired)

Thank you for helping keep LongFiction-AI secure!
