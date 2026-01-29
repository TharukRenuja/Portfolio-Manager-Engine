<div align="center">
  <h1>Portfolio Manager Engine</h1>
  <p>A simple, high-performance headless CMS and personal brand control center.</p>
  <img src="https://i.ibb.co/SXqtRWdq/9cde41912794.png" alt="Portfolio Manager" width="100%">
</div>

## ✨ Features

- **Performance**: Pre-aggregated analytics and intelligent caching.
- **Content**: Manage Blog, Projects, and Downloads with ease.
- **Career**: Built-in Resume Vault and Bio-Link (Linktree) directory.
- **Branding**: Dynamic theme control and auto-branding wizard.
- **Portability**: Full export/restore of your entire database state.
- **Push Notifications**: Receive instant, real-time system alerts.
- **Analytics**: Built-in user behavior tracking and traffic insights.
- **Monitoring**: Integrated health checks for deployments and domains.
- **Security**: Multi-Factor Authentication (TOTP) and one-click maintenance.
- **Multi-Account**: Secure multiple admin accounts with role-based access across devices.


## 📡 API Usage

The Portfolio Manager provides a robust set of JSON endpoints for external frontends.

### 🌎 Public Content
| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/api/settings` | `GET` | Website branding, social URLs, and features |
| `/api/seo` | `GET` | SEO metadata and auto-generated JSON-LD |
| `/api/blog` | `GET` | List all published blog posts |
| `/api/projects` | `GET` | List all projects and case studies |
| `/api/experience` | `GET` | Career timeline and work history |
| `/api/downloads` | `GET` | Software/App download links across platforms |
| `/api/sitemap` | `GET` | Dynamic sitemap structure for search engines |

### 📈 Engagement & Interactions
| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/api/contact` | `POST` | Submit contact form messages |
| `/api/analytics` | `POST` | Log page views and visitor data |
| `/api/blog/<permalink>/update_view` | `POST` | Increment read count for a blog post |
| `/api/projects/<permalink>/update_view` | `POST` | Increment view count for a project |
| `/api/downloads/<id>/hit` | `POST` | Track a file download click |

### 🔐 System & Push
| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/api/push/public-key` | `GET` | Retrieve the VAPID public key |
| `/api/push/subscribe` | `POST` | Register a service worker subscription |
| `/api/health` | `GET` | Basic system health check |

### 🛡️ Administrative (Protected)
| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/api/notifications/new` | `GET` | Poll for new unread messages |
| `/api/notifications/dismiss/<id>` | `DELETE` | Permanently delete a message |
| `/api/upload-image` | `POST` | Upload media to ImgBB and get URL |
| `/api/push/send` | `POST` | Trigger a push notification to all subscribers |
| `/api/export` | `GET` | Export a full encrypted JSON backup |
| `/api/restore` | `POST` | Restore database from a backup file |

## 🛠️ Tech Stack

- **Backend**: Python / Flask
- **Database**: Google Firestore (NoSQL)
- **Deployment**: Vercel / Railway / Google Cloud Run
- **Styling**: Vanilla CSS / Tailwind (Frontend optimized)
- **Integrations**: ImgBB (Media), VAPID (Push Notifications)

## 🚀 Installation

### 1. Prerequisites
- A [Google Firebase](https://console.firebase.google.com/) Project with Firestore enabled
- An [ImgBB](https://api.imgbb.com/) API Key (Free)

### 2. Setup
```bash
# Clone the repository
git clone https://github.com/TharukRenuja/Portfolio-Manager-Engine.git
cd Portfolio-Manager-Engine

# Install dependencies
pip install -r requirements.txt

# Run the application
python main.py
```

### 3. Verification
Visit `http://localhost:5000` to start the setup wizard.
- Enter your **Firebase Config**.
- Enter your **ImgBB API Key**.
- Follow the wizard to initialize your brand.

## 4. Backup & Migration

The system supports full data portability. You can export your entire database from the **Danger Zone** and restore it during setup or via the API to move between projects instantly.

---

Built with ❤️ by [Tharuk Renuja](https://github.com/TharukRenuja)
