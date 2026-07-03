const express = require('express');
const cors = require('cors');
const cookieParser = require('cookie-parser');
const jwt = require('jsonwebtoken');
const bcrypt = require('bcryptjs');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const app = express();
const PORT = process.env.AUTH_PORT || 3001;
if (!process.env.JWT_SECRET) {
  console.error('FATAL: JWT_SECRET environment variable is required');
  process.exit(1);
}
const JWT_SECRET = process.env.JWT_SECRET;
const TOKEN_NAME = 'acronous_token';
const USERS_FILE = path.join(__dirname, 'users.json');

app.use(cors({ origin: true, credentials: true }));
app.use(cookieParser());
app.use(express.json());
app.use(express.urlencoded({ extended: true }));
app.use(express.static(path.join(__dirname, 'public')));

function loadUsers() {
  try {
    if (fs.existsSync(USERS_FILE)) {
      return JSON.parse(fs.readFileSync(USERS_FILE, 'utf-8'));
    }
  } catch (e) {
    console.error('Error loading users:', e.message);
  }
  return [];
}

function saveUsers(users) {
  fs.writeFileSync(USERS_FILE, JSON.stringify(users, null, 2));
}

function generateToken(user) {
  return jwt.sign(
    { id: user.id, email: user.email, name: user.name },
    JWT_SECRET,
    { expiresIn: '7d' }
  );
}

function verifyToken(token) {
  try {
    return jwt.verify(token, JWT_SECRET);
  } catch {
    return null;
  }
}

function setAuthCookie(res, token) {
  res.cookie(TOKEN_NAME, token, {
    domain: '.acronous.com',
    path: '/',
    maxAge: 7 * 24 * 60 * 60 * 1000,
    httpOnly: false,
    sameSite: 'lax',
    secure: process.env.NODE_ENV === 'production',
  });
}

function clearAuthCookie(res) {
  res.clearCookie(TOKEN_NAME, {
    domain: '.acronous.com',
    path: '/',
  });
}

function requireAuth(req, res, next) {
  const token = req.cookies?.[TOKEN_NAME] || req.headers.authorization?.replace('Bearer ', '');
  const decoded = verifyToken(token);
  if (!decoded) {
    return res.redirect('/login?redirect=' + encodeURIComponent(req.originalUrl));
  }
  req.user = decoded;
  next();
}

app.get('/api/auth/verify', (req, res) => {
  const token = req.cookies?.[TOKEN_NAME] || req.headers.authorization?.replace('Bearer ', '');
  const decoded = verifyToken(token);
  if (!decoded) {
    return res.json({ valid: false });
  }
  return res.json({ valid: true, user: { id: decoded.id, email: decoded.email, name: decoded.name } });
});

app.get('/api/auth/me', (req, res) => {
  const token = req.cookies?.[TOKEN_NAME] || req.headers.authorization?.replace('Bearer ', '');
  const decoded = verifyToken(token);
  if (!decoded) {
    return res.status(401).json({ error: 'Not authenticated' });
  }
  return res.json({ user: { id: decoded.id, email: decoded.email, name: decoded.name } });
});

app.post('/api/auth/signup', async (req, res) => {
  try {
    const { email, password, name } = req.body;
    if (!email || !password) {
      return res.status(400).json({ error: 'Email and password are required' });
    }
    if (password.length < 6) {
      return res.status(400).json({ error: 'Password must be at least 6 characters' });
    }

    const users = loadUsers();
    if (users.find(u => u.email === email.toLowerCase())) {
      return res.status(409).json({ error: 'An account with this email already exists' });
    }

    const hashedPassword = await bcrypt.hash(password, 10);
    const newUser = {
      id: crypto.randomUUID(),
      email: email.toLowerCase(),
      name: name || email.split('@')[0],
      password: hashedPassword,
      createdAt: new Date().toISOString(),
    };

    users.push(newUser);
    saveUsers(users);

    const token = generateToken(newUser);
    setAuthCookie(res, token);

    return res.json({ success: true, token, user: { id: newUser.id, email: newUser.email, name: newUser.name } });
  } catch (e) {
    console.error('Signup error:', e);
    return res.status(500).json({ error: 'Something went wrong. Please try again.' });
  }
});

app.post('/api/auth/signup-redirect', async (req, res) => {
  try {
    const { email, password, name } = req.body;
    if (!email || !password) {
      return res.status(400).json({ error: 'Email and password are required' });
    }
    if (password.length < 6) {
      return res.status(400).json({ error: 'Password must be at least 6 characters' });
    }

    const users = loadUsers();
    if (users.find(u => u.email === email.toLowerCase())) {
      return res.status(409).json({ error: 'An account with this email already exists' });
    }

    const hashedPassword = await bcrypt.hash(password, 10);
    const newUser = {
      id: crypto.randomUUID(),
      email: email.toLowerCase(),
      name: name || email.split('@')[0],
      password: hashedPassword,
      createdAt: new Date().toISOString(),
    };

    users.push(newUser);
    saveUsers(users);

    const token = generateToken(newUser);
    setAuthCookie(res, token);

    const redirect = req.body.redirect || '/';
    const target = `${redirect}${redirect.includes('?') ? '&' : '?'}token=${token}`;
    return res.json({ success: true, redirectUrl: target, token });
  } catch (e) {
    console.error('Signup error:', e);
    return res.status(500).json({ error: 'Something went wrong. Please try again.' });
  }
});

app.post('/api/auth/login', async (req, res) => {
  try {
    const { email, password } = req.body;
    if (!email || !password) {
      return res.status(400).json({ error: 'Email and password are required' });
    }

    const users = loadUsers();
    const user = users.find(u => u.email === email.toLowerCase());
    if (!user) {
      return res.status(401).json({ error: 'Invalid email or password' });
    }

    const valid = await bcrypt.compare(password, user.password);
    if (!valid) {
      return res.status(401).json({ error: 'Invalid email or password' });
    }

    const token = generateToken(user);
    setAuthCookie(res, token);

    return res.json({ success: true, token, user: { id: user.id, email: user.email, name: user.name } });
  } catch (e) {
    console.error('Login error:', e);
    return res.status(500).json({ error: 'Something went wrong. Please try again.' });
  }
});

app.post('/api/auth/login-redirect', async (req, res) => {
  try {
    const { email, password } = req.body;
    if (!email || !password) {
      return res.status(400).json({ error: 'Email and password are required' });
    }

    const users = loadUsers();
    const user = users.find(u => u.email === email.toLowerCase());
    if (!user) {
      return res.status(401).json({ error: 'Invalid email or password' });
    }

    const valid = await bcrypt.compare(password, user.password);
    if (!valid) {
      return res.status(401).json({ error: 'Invalid email or password' });
    }

    const token = generateToken(user);
    setAuthCookie(res, token);

    const redirect = req.body.redirect || '/';
    const target = `${redirect}${redirect.includes('?') ? '&' : '?'}token=${token}`;
    return res.json({ success: true, redirectUrl: target, token });
  } catch (e) {
    console.error('Login error:', e);
    return res.status(500).json({ error: 'Something went wrong. Please try again.' });
  }
});

app.post('/api/auth/logout', (req, res) => {
  clearAuthCookie(res);
  return res.json({ success: true });
});

app.get('/', (req, res) => {
  const token = req.cookies?.[TOKEN_NAME];
  if (token && verifyToken(token)) {
    return res.redirect('/dashboard');
  }
  res.redirect('/login');
});

app.get('/login', (req, res) => {
  const token = req.cookies?.[TOKEN_NAME];
  if (token) {
    const decoded = verifyToken(token);
    if (decoded) {
      const redirect = req.query.redirect || '/';
      return res.redirect(redirect);
    }
  }
  res.sendFile(path.join(__dirname, 'public', 'login.html'));
});

app.get('/signup', (req, res) => {
  const token = req.cookies?.[TOKEN_NAME];
  if (token) {
    const decoded = verifyToken(token);
    if (decoded) {
      const redirect = req.query.redirect || '/';
      return res.redirect(redirect);
    }
  }
  res.sendFile(path.join(__dirname, 'public', 'signup.html'));
});

app.get('/dashboard', requireAuth, (req, res) => {
  res.sendFile(path.join(__dirname, 'public', 'dashboard.html'));
});

app.get('/logout', (req, res) => {
  clearAuthCookie(res);
  res.redirect('/login');
});

app.get('/health', (req, res) => {
  res.json({ status: 'ok', users: loadUsers().length });
});

app.listen(PORT, '0.0.0.0', () => {
  console.log(`Acronous Auth Server running on http://localhost:${PORT}`);
  console.log(`Login: http://localhost:${PORT}/login`);
});
