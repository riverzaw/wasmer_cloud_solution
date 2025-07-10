# Cloud Solution GraphQL API

This project provides a GraphQL API for managing deployed applications and users in a cloud solution platform. 
It's built with Django, SQLite and Strawberry GraphQL, featuring asynchronous request handling.

## API Endpoints

- GraphQL endpoint: `/graphql/`

## GraphQL Schema

### Queries

#### Fetch User by ID

```graphql 
query(id: String!) { node(id:id) { ... on UserType { id username plan deployedApps { id active } } } }
```

#### Fetch User's Active Apps Only

```graphql 
query(id: String!) { node(id:id) { ... on UserType { id username plan deployedApps(active: true) { id active } } } }
```

or inactive apps

```graphql 
query(id: String!) { node(id:id) { ... on UserType { id username plan deployedApps(active: false) { id active } } } }
```

#### Fetch Deployed App by ID

```graphql 
query(id: String!) { node(id:id) { ... on DeployedAppType { id active owner { id username } } } }
```


### Mutations

#### Upgrade User Account

```graphql 
mutation(userId: String!) { upgradeAccount(userId:userId) { id username plan } }
```

#### Downgrade User Account

```graphql 
mutation(userId: String!) { downgradeAccount(userId:userId) { id username plan } }
```

## Data Models

### User
- Has a unique ID (prefixed with "u_")
- Username
- Plan type (HOBBY or PRO)
- Can have multiple deployed applications

### DeployedApp
- Has a unique ID (prefixed with "app_")
- Active status (boolean)
- Associated with an owner (User)

## ID Format
Although IDs are global Relay nodes and are encoded in base64, querying users and apps is done by human-readable prefixed ID:
- Users: `u_<user_id>`
- Apps: `app_<app_id>`

A custom Django model manager is used for handling these IDs.

## Error Handling
The API returns appropriate error messages when:
- Requested node doesn't exist
- User not found during account plan changes
- Invalid operations are attempted

## Development

### Requirements
- Python 3.12
- Django
- Strawberry GraphQL
- Starlette

```bash
pip install -r requirements.txt
python manage.py migrate
python manage.py loaddata users deployed_apps providers
```

### Testing
The project includes tests for models, queries and mutations.

Run tests using pytest:

```bash 
pytest
```


### Notes
- All GraphQL operations are handled asynchronously
- The API uses DataLoaders to prevent N+1 query problems


## Email usage scenario

MailerSend and SMTP2Go are used in this project setup. They are both configured to use a dedicated domain.

SMTP2Go allows us to use subdomains, so SMTP2GoProviderClient requests a subdomain for the user when new SMTP credentials are requested.
The users configured in SMTP2Go will have addresses like app_1@user-1.emailchallengeirina.com.

MailerSend allows to configure only one SMTP user in free plan, so in the current project setup the previously created user needs to be deleted manually before a new one can be created.


1.Set active provider for an app (MAILERSEND or SMTP2GO in this case):

```bash
mutation setAppProvider {
  setAppProvider(
    appId: "app_hobby"
    providerName: "SMTP2GO"
  )
}
```

2. Provision credentials with the selected provider:

```bash
mutation provisionCredentials {
  provisionCredentials(
    appId: "app_hobby"
  ){
    provisioningStatus
    provisioningError
    providerName
  }
}
```

This mutation will trigger a background job creating credentials for the new user via email provider API.
If the credentials have been already configured, the mutation will return the error message:

```bash
"Credentials have been already configured for this app and provider."
```


3. The user can poll for status of the credentials provisioning:

```bash
query getProvisionStatus {
  appSendingConfiguration(appId: "app_hobby") {
    provisioningStatus
    provisioningError
  }
} 
```

The provisioning status of the credentials will be set to SUCCESS once the provider returns the credentials to the background job.


4. The user can now send an email with a mutation:

```bash
mutation sendEmail {
  sendEmail(
  appId: "app_hobby"
  to: "hello@gmail.com"
  subject: "Hi there"
  html: "<body>This is an email.</body>"
)}
```

If owner of app is on HOBBY plan, their credits are deducted by 1. If they don't have credits, the mutation show an error:

```"Insufficient credits."```

The mutation will trigger a background job sending email via SMTP with the provider which is configured as active for the app.

The job creates an entry in SentEmailLog table initially setting email status to QUEUED.
In case of email sending failure, the status will be set to FAILED and error message will be added to the entry in SentEmailLog.
When email has been successfully processed via the background job, its status is set to SENT.
Further status updates are handled via webhooks from providers. 
Currently MailerSend and SMTP2Go are configured to send "delivered" and "opened" notifications which 
result in DELIVERED and OPENED statuses accordingly.
The field `time_read` is set to the time of "opened" event.


5. The user can query for their SMTP credentials:

```bash
mutation getSmtpCredentials {
  getSmtpCredentials(appId: "app_hobby") {
    host
    port
    username
    password
    provider
  }
}
```

6. Users and apps queries show their email statistics:

```bash
query getAppEmails {
  node(id: "app_hobby") {
    ... on DeployedAppType {
      id
      totalEmailsCount
      usage(groupBy: DAY | WEEK | MONTH, timeWindow: ["2025-07-01", "2025-07-03"]) {
        timestamp
        emails {
          total
          failed
          read
          sent
        }
      }
    }
  }
}
```


```bash
query getUserEmails {
  node(id: "u_hobbyist") {
    ... on UserType {
          id
          username
          plan
          emails {
            sentEmailsCount
            usage(groupBy: DAY, timeWindow: [start, end]) {
              timestamp
              emails {
                total
                failed
                read
                sent
              }
            }
        }
      }
  }
}


```



## Celery tasks

1. **GraphQL Mutation**: When `sendEmail` is called, it immediately returns `true` and queues a background task.

2. **Credit Check Task**: `send_email_with_credit_check`
   - Checks if the user has sufficient credits (for hobby plan users)
   - Deducts credits if needed
   - Queues the actual email sending task
   - Called from GraphQL mutation

3. **Email Sending Task**: The `send_email_task`:
   - Retrieves the app's SMTP configuration
   - Gets the appropriate provider client (MailerSend, SMTP2Go, etc.)
   - Sends the email via SMTP
   - Updates usage statistics (sent/failed counts)
   - Retries up to 3 times on failure
   - Called from: `send_email_with_credit_check` task

4. **Set active provider Task**: `set_app_provider_task`
   - Changes active provider for the app. Exactly one provider is always active for the app.
   - Called from: GraphQL mutation

5. **Provision credentials for app**: `provision_credentials_for_app_task`
   - Calls active provider method for creating credentials for the app
   - Called from GraphQL mutation
