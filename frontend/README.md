# GraphRAG Frontend

Next.js frontend for the GraphRAG chat interface.

## Setup

### 1. Install Dependencies

```bash
cd frontend
npm install
```

### 2. Environment Variables

Create `.env.local` file:

```bash
NEXT_PUBLIC_API_URL=http://localhost:8000
```

### 3. Run Development Server

```bash
npm run dev
```

Open [http://localhost:3002](http://localhost:3002) in your browser.

### 4. Build for Production

```bash
npm run build
npm start
```

## Project Structure

```
frontend/
├── app/              # Next.js App Router pages
├── components/       # React components
├── lib/             # Utilities and API client
└── public/          # Static assets
```

## Features

- Chat interface with message history
- Cypher query display with syntax highlighting
- Results table visualization
- Similar examples display
- Error handling
- Loading states

## Deployment

### Azure Static Web Apps

1. Connect GitHub repository
2. Configure build settings:
   - App location: `frontend`
   - Api location: (leave empty, API is separate)
   - Output location: `.next`
3. Set environment variable: `NEXT_PUBLIC_API_URL`

### Azure App Service

1. Build the app: `npm run build`
2. Deploy `.next` folder to Azure App Service
3. Configure environment variables

