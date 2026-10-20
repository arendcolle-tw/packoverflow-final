const http = require("http");

const page = `<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PackOverflow</title>
<style>
  body { margin: 0; min-height: 100vh; display: grid; place-items: center;
         font-family: system-ui, sans-serif; background: #0f172a; color: #f8fafc; }
  main { text-align: center; padding: 16px; }
  h1 { font-size: 3rem; margin: 0 0 .5rem; }
  p { color: #94a3b8; }
</style></head>
<body><main><h1>PackOverflow is live</h1><p>Tectonic Hackathon final, SD Worx track.</p></main></body></html>`;

const server = http.createServer((req, res) => {
  if (req.url === "/healthz") {
    res.writeHead(200, { "Content-Type": "text/plain" });
    return res.end("ok");
  }
  res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
  res.end(page);
});

const port = process.env.PORT || 8080;
server.listen(port, () => console.log(`listening on ${port}`));
