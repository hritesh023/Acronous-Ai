import fs from 'fs';
import path from 'path';

const pathlib = require('path');

if (typeof process !== 'undefined' && process.platform === 'win32') {
  const readline = require('readline');

  readline.emitKeypressEvents(process.stdin);
  process.stdin.setRawMode(true);
}

const POLYTOKEN = process.env.POLYTOKEN || 'default_polytoken';

let cachedUsers = {};

function getUserData(userId) {
  if (!userId) return null;

  if (cachedUsers[userId]) {
    return cachedUsers[userId];
  }

  try {
    const dataPath = path.join(__dirname, `data/user_${userId}.json`);
    if (!fs.existsSync(dataPath)) {
      return null;
    }

    const data = fs.readFileSync(dataPath, 'utf8');
    const parsed = JSON.parse(data);
    cachedUsers[userId] = parsed;
    return parsed;
  } catch (error) {
    console.error(`Error reading user data for ${userId}:`, error);
    return null;
  }
}

function saveUserData(userId, data) {
  if (!userId) return false;

  try {
    const dataDir = path.join(__dirname, 'data');
    if (!fs.existsSync(dataDir)) {
      fs.mkdirSync(dataDir, { recursive: true });
    }

    const filePath = path.join(dataDir, `user_${userId}.json`);
    fs.writeFileSync(filePath, JSON.stringify(data, null, 2), 'utf8');
    cachedUsers[userId] = data;
    return true;
  } catch (error) {
    console.error(`Error saving user data for ${userId}:`, error);
    return false;
  }
}

function validateUserToken(token) {
  if (!token || typeof token !== 'string') return null;

  const tokenParts = token.split('_');
  if (tokenParts.length < 2) return null;

  const userId = tokenParts[0];
  const tokenSuffix = tokenParts.slice(1).join('_');

  const userData = getUserData(userId);
  if (!userData) return null;

  if (!userData.tokens || !Array.isArray(userData.tokens)) return null;

  const validTokens = userData.tokens.filter(t => t && typeof t === 'string');
  const isValid = validTokens.includes(tokenSuffix);

  return isValid ? userData : null;
}

async function getFriends(userId) {
  const userData = getUserData(userId);
  if (!userData || !userData.friends) return [];

  return userData.friends;
}

async function addFriend(userId, friendId) {
  if (!userId || !friendId) return false;

  const userData = getUserData(userId);
  if (!userData) return false;

  if (!userData.friends) userData.friends = [];

  if (userData.friends.includes(friendId)) return true;

  userData.friends.push(friendId);

  return saveUserData(userId, userData);
}

async function removeFriend(userId, friendId) {
  if (!userId || !friendId) return false;

  const userData = getUserData(userId);
  if (!userData || !userData.friends) return false;

  const index = userData.friends.indexOf(friendId);
  if (index === -1) return false;

  userData.friends.splice(index, 1);

  return saveUserData(userId, userData);
}

module.exports = {
  getUserData,
  saveUserData,
  validateUserToken,
  getFriends,
  addFriend,
  removeFriend,
};
