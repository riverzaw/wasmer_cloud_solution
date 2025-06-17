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
```

### Testing
The project includes tests for models, queries and mutations.

Run tests using pytest:

```bash 
pytest
```


## Notes
- All GraphQL operations are handled asynchronously
- The API uses DataLoaders to prevent N+1 query problems
