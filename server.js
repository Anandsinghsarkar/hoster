const express = require('express');
const multer = require('multer');
const AdmZip = require('adm-zip');
const { spawn, exec } = require('child_process');
const fs = require('fs');
const path = require('path');
const cors = require('cors');

const app = express();
const PORT = process.env.PORT || 3000;

app.use(cors());
app.use(express.json());
// Serve the frontend UI from 'public' folder
app.use(express.static(path.join(__dirname, 'public'))); 

// Make sure bots directory exists
const BOTS_DIR = path.join(__dirname, 'bots');
if (!fs.existsSync(BOTS_DIR)) fs.mkdirSync(BOTS_DIR);

// In-memory state for running bots
const runningBots = {}; 
/* format: 
{
    "bot_id": {
        process: <ChildProcess>,
        logs: ["log line 1", "log line 2"]
    }
}
*/

// --- Helper Functions ---
function getBotDir(id) { return path.join(BOTS_DIR, id); }
function getBotSrcDir(id) { return path.join(BOTS_DIR, id, 'src'); }
function getBotConfigFile(id) { return path.join(BOTS_DIR, id, 'config.json'); }

function addLog(id, msg) {
    if (!runningBots[id]) runningBots[id] = { logs: [] };
    const timestamp = new Date().toLocaleTimeString();
    runningBots[id].logs.push(`[${timestamp}] ${msg}`);
    // Keep only last 500 lines to save memory
    if (runningBots[id].logs.length > 500) runningBots[id].logs.shift();
}

// Multer setup for file uploads
const upload = multer({ dest: 'uploads/' });

// --- API Endpoints ---

// 1. Get all bots
app.get('/api/bots', (req, res) => {
    const bots = [];
    const dirs = fs.readdirSync(BOTS_DIR);
    dirs.forEach(id => {
        const configPath = getBotConfigFile(id);
        if (fs.existsSync(configPath)) {
            const config = JSON.parse(fs.readFileSync(configPath, 'utf8'));
            config.status = runningBots[id] && runningBots[id].process ? 'online' : 'offline';
            bots.push(config);
        }
    });
    res.json(bots);
});

// 2. Create a new bot slot
app.post('/api/bots', (req, res) => {
    const id = 'bot_' + Math.random().toString(36).substr(2, 9);
    fs.mkdirSync(getBotDir(id));
    fs.mkdirSync(getBotSrcDir(id));
    
    const config = {
        id: id,
        name: req.body.name || `Bot ${id.substr(4,4)}`,
        token: '',
        mainScript: 'main.py',
        envVars: {},
        fileName: null
    };
    
    fs.writeFileSync(getBotConfigFile(id), JSON.stringify(config, null, 2));
    runningBots[id] = { logs: [`System initialized for ${config.name}. Waiting for files...`] };
    
    res.json(config);
});

// 3. Upload File (.py or .zip)
app.post('/api/bots/:id/upload', upload.single('file'), (req, res) => {
    const id = req.params.id;
    const file = req.file;
    if (!file) return res.status(400).json({ error: 'No file uploaded' });

    const srcDir = getBotSrcDir(id);
    const originalName = file.originalname;

    try {
        if (originalName.endsWith('.zip')) {
            const zip = new AdmZip(file.path);
            zip.extractAllTo(srcDir, true);
            addLog(id, `Success: Extracted ${originalName} into source directory.`);
        } else {
            // Move .py file directly
            fs.renameSync(file.path, path.join(srcDir, originalName));
            addLog(id, `Success: Saved script ${originalName}.`);
        }
        
        // Cleanup multer temp file if not moved
        if(fs.existsSync(file.path)) fs.unlinkSync(file.path);

        // Update config with filename
        const configPath = getBotConfigFile(id);
        const config = JSON.parse(fs.readFileSync(configPath, 'utf8'));
        config.fileName = originalName;
        fs.writeFileSync(configPath, JSON.stringify(config, null, 2));

        res.json({ success: true, fileName: originalName });
    } catch (e) {
        addLog(id, `Error processing file: ${e.message}`);
        res.status(500).json({ error: e.message });
    }
});

// 4. Save Config & Env Vars
app.post('/api/bots/:id/config', (req, res) => {
    const id = req.params.id;
    const configPath = getBotConfigFile(id);
    
    if (fs.existsSync(configPath)) {
        const config = JSON.parse(fs.readFileSync(configPath, 'utf8'));
        const updatedConfig = { ...config, ...req.body };
        fs.writeFileSync(configPath, JSON.stringify(updatedConfig, null, 2));
        res.json({ success: true });
    } else {
        res.status(404).json({ error: 'Bot not found' });
    }
});

// 5. Start Bot
app.post('/api/bots/:id/start', (req, res) => {
    const id = req.params.id;
    const configPath = getBotConfigFile(id);
    
    if (!fs.existsSync(configPath)) return res.status(404).json({ error: 'Bot not found' });
    
    const config = JSON.parse(fs.readFileSync(configPath, 'utf8'));
    const srcDir = getBotSrcDir(id);
    const scriptPath = path.join(srcDir, config.mainScript);

    if (runningBots[id] && runningBots[id].process) {
        return res.status(400).json({ error: 'Bot is already running' });
    }

    addLog(id, `Starting bot using python3 ${config.mainScript}...`);

    // Prepare Environment Variables
    const processEnv = { ...process.env, ...config.envVars, BOT_TOKEN: config.token };

    try {
        const pyProcess = spawn('python3', [config.mainScript], {
            cwd: srcDir,
            env: processEnv
        });

        if (!runningBots[id]) runningBots[id] = { logs: [] };
        runningBots[id].process = pyProcess;

        pyProcess.stdout.on('data', (data) => addLog(id, data.toString().trim()));
        pyProcess.stderr.on('data', (data) => addLog(id, `ERROR: ${data.toString().trim()}`));
        
        pyProcess.on('close', (code) => {
            addLog(id, `Process exited with code ${code}`);
            if (runningBots[id]) runningBots[id].process = null;
        });

        res.json({ success: true });
    } catch (e) {
        addLog(id, `Failed to start: ${e.message}`);
        res.status(500).json({ error: e.message });
    }
});

// 6. Stop Bot
app.post('/api/bots/:id/stop', (req, res) => {
    const id = req.params.id;
    if (runningBots[id] && runningBots[id].process) {
        addLog(id, `Sending kill signal to bot...`);
        runningBots[id].process.kill('SIGINT');
        runningBots[id].process = null;
        res.json({ success: true });
    } else {
        res.status(400).json({ error: 'Bot is not running' });
    }
});

// 7. Get Logs
app.get('/api/bots/:id/logs', (req, res) => {
    const id = req.params.id;
    const logs = runningBots[id] ? runningBots[id].logs : [];
    res.json({ logs });
});

// 8. Terminal Command Execution (Bash or Stdin)
app.post('/api/bots/:id/command', (req, res) => {
    const id = req.params.id;
    const cmd = req.body.command;
    const srcDir = getBotSrcDir(id);

    if (!cmd) return res.status(400).json({ error: 'No command provided' });

    addLog(id, `> ${cmd}`);

    // If python process is running, send to its stdin
    if (runningBots[id] && runningBots[id].process) {
        try {
            runningBots[id].process.stdin.write(cmd + '\n');
            return res.json({ success: true, type: 'stdin' });
        } catch (e) {
            addLog(id, `Error writing to stdin: ${e.message}`);
        }
    }

    // If not running, execute as a shell command (useful for pip install)
    exec(cmd, { cwd: srcDir }, (error, stdout, stderr) => {
        if (stdout) addLog(id, stdout.trim());
        if (stderr) addLog(id, stderr.trim());
        if (error) addLog(id, `Execution Error: ${error.message}`);
    });
    
    res.json({ success: true, type: 'shell' });
});

// Start Server
app.listen(PORT, () => {
    console.log(`TeleHost Backend running on http://localhost:${PORT}`);
});