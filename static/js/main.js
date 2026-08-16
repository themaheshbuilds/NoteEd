// Theme Toggle
function initTheme() {
  const theme = localStorage.getItem('theme') || 'dark';
  document.body.className = theme;
  const themeToggleBtn = document.getElementById('theme-toggle');
  if (themeToggleBtn) {
    themeToggleBtn.innerText = theme === 'dark' ? '☀️ Light Mode' : '🌙 Dark Mode';
  }
}

function toggleTheme() {
  const currentTheme = document.body.className;
  const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
  document.body.className = newTheme;
  localStorage.setItem('theme', newTheme);
  const themeToggleBtn = document.getElementById('theme-toggle');
  if (themeToggleBtn) {
    themeToggleBtn.innerText = newTheme === 'dark' ? '☀️ Light Mode' : '🌙 Dark Mode';
  }
}

// Pomodoro Timer
let pomodoroInterval;
let timeLeft = 25 * 60;
let isRunning = false;

function updateTimerDisplay() {
  const minutes = Math.floor(timeLeft / 60);
  const seconds = timeLeft % 60;
  const timerDisplay = document.getElementById('pomodoro-display');
  if (timerDisplay) {
    timerDisplay.innerText = `${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
  }
}

function togglePomodoro() {
  const btn = document.getElementById('pomodoro-toggle');
  if (isRunning) {
    clearInterval(pomodoroInterval);
    isRunning = false;
    btn.innerText = 'Start';
  } else {
    isRunning = true;
    btn.innerText = 'Pause';
    pomodoroInterval = setInterval(() => {
      if (timeLeft > 0) {
        timeLeft--;
        updateTimerDisplay();
      } else {
        clearInterval(pomodoroInterval);
        isRunning = false;
        btn.innerText = 'Start';
        alert('Pomodoro session completed! Time for a short break.');
        timeLeft = 25 * 60;
        updateTimerDisplay();
      }
    }, 1000);
  }
}

function resetPomodoro() {
  clearInterval(pomodoroInterval);
  isRunning = false;
  timeLeft = 25 * 60;
  updateTimerDisplay();
  const btn = document.getElementById('pomodoro-toggle');
  if (btn) btn.innerText = 'Start';
}

document.addEventListener('DOMContentLoaded', () => {
  initTheme();
  updateTimerDisplay();
  
  const themeToggleBtn = document.getElementById('theme-toggle');
  if (themeToggleBtn) {
    themeToggleBtn.addEventListener('click', toggleTheme);
  }
});

