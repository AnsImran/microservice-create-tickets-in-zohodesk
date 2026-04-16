# microservice-create-zoho-desk-ticket

Microservice that creates Zoho Desk tickets via the Zoho Desk REST API.

## Architecture

### Module Dependency & Import Graph

Every module, what it exports, and how they connect to serve the main objective: **accept a JSON request and create a Zoho Desk ticket**.

```mermaid
graph TB
    classDef entry fill:#4CAF50,stroke:#2E7D32,color:#fff,stroke-width:2px
    classDef app fill:#2196F3,stroke:#1565C0,color:#fff,stroke-width:2px
    classDef client fill:#FF9800,stroke:#E65100,color:#fff,stroke-width:2px
    classDef schema fill:#9C27B0,stroke:#6A1B9A,color:#fff,stroke-width:2px
    classDef config fill:#607D8B,stroke:#37474F,color:#fff,stroke-width:2px
    classDef external fill:#F44336,stroke:#B71C1C,color:#fff,stroke-width:2px,stroke-dasharray: 5 5

    UVICORN["uvicorn src.app.main:app<br/><i>Entry point</i>"]:::entry

    subgraph "src/app/"
        MAIN["main.py<br/><b>FastAPI app</b><br/>Routes + exception handlers"]:::app
        CONFIG["config.py<br/><b>Settings</b><br/>ENV_PATH, settings singleton"]:::config
    end

    subgraph "src/schemas/"
        TICKETS["tickets.py<br/><b>ContactModel</b><br/><b>TicketRequest</b><br/><b>TicketResponse</b>"]:::schema
    end

    subgraph "src/clients/"
        TOKEN["token_client.py<br/><b>get_access_token()</b><br/><b>TokenServiceError</b>"]:::client
        ZOHO["zoho_desk.py<br/><b>create_ticket()</b><br/><b>resolve_product_id()</b><br/><b>ZohoDeskError</b><br/><b>ProductNotFoundError</b>"]:::client
    end

    ENV[".env file<br/>PRODUCT_MAP, ORG_ID, ..."]:::config
    TOKEN_SVC["zoho_token_service<br/><i>:8000</i>"]:::external
    ZOHO_API["Zoho Desk API<br/><i>desk.zoho.com</i>"]:::external

    UVICORN -->|"loads"| MAIN
    MAIN -->|"imports create_ticket"| ZOHO
    MAIN -->|"imports get_access_token,<br/>TokenServiceError"| TOKEN
    MAIN -->|"imports TicketRequest,<br/>TicketResponse"| TICKETS
    MAIN -->|"imports settings"| CONFIG

    ZOHO -->|"imports get_access_token"| TOKEN
    ZOHO -->|"imports TicketRequest,<br/>TicketResponse"| TICKETS
    ZOHO -->|"imports settings,<br/>ENV_PATH"| CONFIG
    ZOHO -.->|"reads/writes<br/>PRODUCT_MAP"| ENV

    TOKEN -->|"imports settings"| CONFIG

    CONFIG -.->|"reads at startup"| ENV

    TOKEN -.->|"GET /v1/token"| TOKEN_SVC
    ZOHO -.->|"POST /api/v1/tickets<br/>GET /api/v1/products"| ZOHO_API
```

### Request Lifecycle — Ticket Creation

Full lifecycle from the moment a caller hits `POST /v1/tickets` to the Zoho Desk ticket appearing in the UI.

```mermaid
sequenceDiagram
    autonumber

    participant Caller as Caller<br/>(Stroke Workflow)
    participant Main as src/app/main.py<br/>FastAPI Router
    participant ZohoDesk as src/clients/zoho_desk.py<br/>create_ticket()
    participant ProdMap as .env file<br/>PRODUCT_MAP
    participant ZohoAPI_P as Zoho Desk API<br/>/api/v1/products
    participant TokenClient as src/clients/token_client.py<br/>get_access_token()
    participant TokenSvc as zoho_token_service<br/>:8000
    participant ZohoAPI_T as Zoho Desk API<br/>/api/v1/tickets

    rect rgb(232, 245, 233)
        Note over Caller,Main: 1. Incoming Request
        Caller->>+Main: POST /v1/tickets<br/>{ subject, description, contact,<br/>  productName, departmentId, ... }
        Main->>Main: Validate request body<br/>via TicketRequest schema
    end

    Main->>+ZohoDesk: create_ticket(req)

    rect rgb(227, 242, 253)
        Note over ZohoDesk,ZohoDesk: 2. Resolve Department
        ZohoDesk->>ZohoDesk: departmentId = req.departmentId<br/>or settings.default
        Note over ZohoDesk: ValueError if neither set
    end

    rect rgb(255, 243, 224)
        Note over ZohoDesk,TokenSvc: 3. Get Access Token
        ZohoDesk->>+TokenClient: get_access_token()
        TokenClient->>+TokenSvc: GET /v1/token
        TokenSvc-->>-TokenClient: { access_token: "1000.xxx..." }
        TokenClient-->>-ZohoDesk: "1000.xxx..."
    end

    rect rgb(243, 229, 245)
        Note over ZohoDesk,ZohoAPI_P: 4. Resolve Product ID
        alt productId provided in request
            ZohoDesk->>ZohoDesk: Use productId directly
        else productName provided
            ZohoDesk->>+ProdMap: Read PRODUCT_MAP from .env
            ProdMap-->>-ZohoDesk: { name: id, ... }
            alt Found in local map
                ZohoDesk->>ZohoDesk: Return cached productId<br/>(0 API calls)
            else Not in local map
                ZohoDesk->>+ZohoAPI_P: GET /api/v1/products?limit=100
                ZohoAPI_P-->>-ZohoDesk: [ { productName, id }, ... ]
                alt Found in API response
                    ZohoDesk->>ProdMap: Append new name:id<br/>to PRODUCT_MAP in .env
                    ZohoDesk->>ZohoDesk: Return productId
                else Not found anywhere
                    ZohoDesk-->>Main: raise ProductNotFoundError
                    Main-->>Caller: 422 { detail: "Product not found" }
                end
            end
        else Neither provided
            ZohoDesk->>ZohoDesk: Skip product field
        end
    end

    rect rgb(232, 245, 233)
        Note over ZohoDesk,ZohoAPI_T: 5. Create Ticket
        ZohoDesk->>ZohoDesk: Build JSON payload<br/>(subject, description, departmentId,<br/>contact, productId, priority, ...)
        ZohoDesk->>+ZohoAPI_T: POST /api/v1/tickets<br/>Headers: Zoho-oauthtoken, orgId
        ZohoAPI_T-->>-ZohoDesk: { id, ticketNumber, webUrl, ... }
    end

    ZohoDesk-->>-Main: TicketResponse

    rect rgb(252, 228, 236)
        Note over Main,Caller: 6. Response
        Main-->>-Caller: 200 { id, ticketNumber,<br/>webUrl, subject, raw }
    end
```

### Error Handling

How exceptions bubble up from the clients to the caller as meaningful HTTP status codes.

```mermaid
flowchart LR
    classDef err fill:#EF5350,stroke:#B71C1C,color:#fff,stroke-width:2px
    classDef warn fill:#FFA726,stroke:#E65100,color:#fff,stroke-width:2px
    classDef info fill:#42A5F5,stroke:#1565C0,color:#fff,stroke-width:2px
    classDef ok fill:#66BB6A,stroke:#2E7D32,color:#fff,stroke-width:2px

    TSE["TokenServiceError<br/><i>Token service down</i>"]:::err -->|"503"| R503["503 Service<br/>Unavailable"]:::err
    ZDE["ZohoDeskError<br/><i>Zoho API rejected</i>"]:::warn -->|"502"| R502["502 Bad Gateway"]:::warn
    PNF["ProductNotFoundError<br/><i>Unknown product name</i>"]:::info -->|"422"| R422["422 Unprocessable<br/>Entity"]:::info
    VE["ValueError<br/><i>Missing departmentId</i>"]:::info -->|"400"| R400["400 Bad Request"]:::info
    OK["Ticket created"]:::ok -->|"200"| R200["200 OK<br/>TicketResponse"]:::ok
```

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager
- The **zoho_token_service** running locally (provides Zoho OAuth access tokens)

## Setup

```bash
cp .env.example .env
# Fill in ZOHO_DESK_ORG_ID (required) and ZOHO_DESK_DEFAULT_DEPARTMENT_ID (optional)
uv sync
```

## Run

```bash
uv run uvicorn src.app.main:app --host 0.0.0.0 --port 8100 --workers 1
```

Interactive docs at `http://127.0.0.1:8100/docs`.

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `ZOHO_TOKEN_SERVICE_URL` | No | `http://127.0.0.1:8000/v1/token` | URL of the centralised token service |
| `ZOHO_DESK_BASE` | No | `https://desk.zoho.com` | Zoho Desk API base URL |
| `ZOHO_DESK_ORG_ID` | **Yes** | -- | Zoho organisation ID (sent as `orgId` header) |
| `ZOHO_DESK_DEFAULT_DEPARTMENT_ID` | No | -- | Fallback department ID if not provided in request |
| `HTTP_TIMEOUT_SECONDS` | No | `30` | Timeout for outgoing HTTP calls |
| `LOG_LEVEL` | No | `INFO` | Logging level |
| `PRODUCT_MAP` | No | -- | Comma-separated `name:id` pairs for product resolution |

## API

### `POST /v1/tickets`

Create a Zoho Desk ticket.

```bash
curl -X POST http://127.0.0.1:8100/v1/tickets \
  -H "Content-Type: application/json" \
  -d '{
    "subject": "Code Stroke Alert - Test",
    "description": "<p>Test ticket</p>",
    "contact": {"lastName": "Test Patient"},
    "productName": "Code Stroke Alert"
  }'
```

**Request body fields:**

| Field | Type | Required | Notes |
|---|---|---|---|
| `subject` | string | Yes | Ticket subject |
| `description` | string | Yes | HTML or plain-text body |
| `contact` | object | Yes | Must include `lastName`; optional `firstName`, `email`, `phone` |
| `departmentId` | string | No | Falls back to `ZOHO_DESK_DEFAULT_DEPARTMENT_ID` |
| `productId` | string | No | Zoho product ID (preferred -- skips lookup) |
| `productName` | string | No | Human-readable name -- resolved to `productId` via `PRODUCT_MAP` or Zoho API |
| `channel` | string | No | e.g. `"Phone"`, `"Email"`, `"SMS"` |
| `priority` | string | No | e.g. `"High"`, `"Low"` |
| `status` | string | No | e.g. `"Open"`, `"Escalated"` |
| `phone` | string | No | Customer phone |
| `email` | string | No | Customer email |
| `category` | string | No | Ticket category |
| `classification` | string | No | Ticket classification |
| `extra` | object | No | Arbitrary key-value pairs merged into the Zoho payload |

**Response:**

```json
{
  "id": "1166045000006881756",
  "ticketNumber": "6846",
  "webUrl": "https://desk.zoho.com/support/webzter/ShowHomePage.do#Cases/dv/1166045000006881756",
  "subject": "Code Stroke Alert - Test",
  "raw": { }
}
```

### `GET /v1/healthz`

Returns `{"status": "ok"}`.

### `GET /v1/readyz`

Checks connectivity to the token service. Returns 200 or 503.

## Product Resolution

The `PRODUCT_MAP` in `.env` stores a local `name:id` mapping so most requests resolve products with **zero API calls**:

```
PRODUCT_MAP="Code Stroke Alert:1166045000001146278,Amendments:1166045000001146306,..."
```

If a `productName` is not found in the local map, the service fetches the full product list from `GET /api/v1/products`, resolves the ID, and **auto-appends** the new mapping to `.env` so future requests are instant. You can also hand-edit `.env` at any time -- changes are picked up on the next request without restarting.
