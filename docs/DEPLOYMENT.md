# Deployment Instructions

## Option 1: GitHub Pages (Recommended)

1. Create a new repository on GitHub
2. Upload all files from the deploy folder to the repository
3. Go to Settings > Pages
4. Select "Deploy from a branch"
5. Choose "main" branch and "/ (root)" folder
6. Click "Save"

## Option 2: Netlify

1. Go to netlify.com
2. Drag and drop the deploy folder
3. Your site will be live instantly

## Option 3: Vercel

1. Go to vercel.com
2. Import your GitHub repository
3. Deploy automatically

## Option 4: Local Testing

1. Open index.html in a web browser
2. Or use a local server:
   ```bash
   python -m http.server 8000
   ```
   Then visit http://localhost:8000

## 🔗 Update Bot URL

After deployment, update your bot's mini app URL to point to your new deployment.

Example:
```javascript
const mev_stats_url = "https://yourusername.github.io/your-repo-name/";
```
