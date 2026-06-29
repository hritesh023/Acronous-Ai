// Fix subdomain URLs — match current protocol and port so links
// work in local dev (port 8080) and production (standard ports).
function fixSubdomainLinks() {
  const port = window.location.port;
  const proto = window.location.protocol;
  document.querySelectorAll('a[href*=".acronous.com"]').forEach(a => {
    const url = new URL(a.href);
    if (url.hostname.endsWith('.acronous.com') || url.hostname === 'acronous.com') {
      url.protocol = proto;
      if (port && port !== '80' && port !== '443') {
        url.port = port;
      } else {
        url.port = '';
      }
      a.href = url.toString();
    }
  });
}

document.addEventListener('DOMContentLoaded', () => {
  fixSubdomainLinks();

  const navToggle = document.querySelector('.nav-toggle');
  const navLinks = document.querySelector('.nav-links');

  if (navToggle) {
    navToggle.addEventListener('click', () => {
      navToggle.classList.toggle('active');
      navLinks.classList.toggle('open');
    });
  }

  document.querySelectorAll('.nav-link').forEach(link => {
    link.addEventListener('click', () => {
      navToggle.classList.remove('active');
      navLinks.classList.remove('open');
    });
  });

  const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        entry.target.classList.add('visible');
      }
    });
  }, { threshold: 0.1, rootMargin: '0px 0px -40px 0px' });

  document.querySelectorAll('.product-card, .section-header, .hero-content, .vision-content, .vision-visual, .cta-container').forEach(el => {
    el.classList.add('animate-in');
    observer.observe(el);
  });

  document.querySelectorAll('.product-card').forEach(card => {
    card.addEventListener('mousemove', (e) => {
      const rect = card.getBoundingClientRect();
      const x = ((e.clientX - rect.left) / rect.width) * 100;
      const y = ((e.clientY - rect.top) / rect.height) * 100;
      const glow = card.querySelector('.card-glow');
      if (glow) {
        glow.style.setProperty('--mx', x + '%');
        glow.style.setProperty('--my', y + '%');
      }
    });
  });

  window.addEventListener('scroll', () => {
    const navbar = document.querySelector('.navbar');
    if (window.scrollY > 50) {
      navbar.style.background = 'rgba(7,7,14,0.95)';
    } else {
      navbar.style.background = 'rgba(7,7,14,0.85)';
    }
  });

});