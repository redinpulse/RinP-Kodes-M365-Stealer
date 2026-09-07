# Kodes M365 Red Team End-to-End Flow

## Component graph

```mermaid
graph TB
    subgraph "Victim device"
        client["Kodes client\n(src/client)"]
        socks["SOCKS5 server\n(RFC 1929 auth)"]
        ngrokc["ngrok TCP tunnel"]
    end

    subgraph "Kodes server"
        api["Device endpoint\n(/?h=&c=&url=)"]
        panel["Operator panel\n(Flask + Alpine)"]
        mint["Token minting\n(TOKEN_SERVICES)"]
        viewer["Data Viewer\n(DATA_RESOURCES)"]
        db[(SQLite\ndatabase/kodes.db)]
    end

    subgraph "PowerShell modules"
        tt["TokenTactics\n(device code + RefreshTo*)"]
        aad["AADInternals\n(Teams messages)"]
    end

    msft[Microsoft\nlogin / graph / outlook\nsharepoint / azure]

    client -->|"1. register + campaign token"| api
    api -->|"2. device code (ANSI-parsed)"| client
    client -->|"3. user signs in"| msft
    msft -->|"4. tokens → TokenLog.log"| api
    api -->|"5. attribute + encrypt"| db
    panel -->|"6. mint service token"| mint
    mint --> tt
    tt --> msft
    panel -->|"7. fetch data (First N / All)"| viewer
    viewer -->|"direct REST"| msft
    panel -->|"8. Teams messages (async cache)"| aad
    aad --> msft
    client -->|"9. tunnel URL (validated)"| api
    operator[Operator] --> panel
    operator -->|"10. SOCKS5 via ngrok"| socks
    socks --> ngrokc
```

## Registration-to-pivot sequence

```mermaid
sequenceDiagram
    participant C as Client (victim)
    participant S as Server
    participant PS as TokenTactics / AADInternals
    participant M as Microsoft
    participant O as Operator

    C->>S: register ?h=host&c=campaign (validated)
    S->>PS: Get-AzureToken session
    PS-->>S: user_code
    S-->>C: user_code
    C->>M: open devicelogin, auto-enter code (OpenCV + paste)
    M-->>C: authenticated
    C->>C: SOCKS5 + ngrok TCP up
    C->>S: health check / tunnel URL (tcp:// validated)
    Note over S: TokenLog → attribute → Fernet-encrypt<br/>identity + scopes/roles + expiry

    O->>S: login (access key)
    O->>S: device detail → Permission Analysis
    O->>S: mint service token (★ recommended)
    S->>PS: Invoke-RefreshTo*Token -domain <validated>
    PS-->>S: service token (encrypted to service_tokens JSON)
    O->>S: Data Viewer: Fetch First N / Fetch All
    S->>M: direct REST (graph/outlook/sp/azure)
    M-->>S: items (paged, capped 5000)
    O->>M: SOCKS5 through ngrok → victim network egress
```

## References

- AADInternals: <https://github.com/Gerenios/AADInternals>
- AADInternals phishing: <https://aadinternals.com/post/phishing/>
- TokenTactics: <https://github.com/rvrsh3ll/TokenTactics> (vendored, v0.0.2)
