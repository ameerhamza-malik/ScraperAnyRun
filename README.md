# ANY.RUN Malware Analysis Dataset Builder

**Comprehensive scraping solution for building a malware analysis dataset from ANY.RUN sandbox reports**

---

## 🎯 Overview

This workspace contains **two scrapers** and analysis tools for building a comprehensive malware analysis dataset:

1. **URL Collector** (`any_run_scraper.py`) - Collects report URLs ✅ *Already complete*
2. **Report Scraper** (`report_scraper.py`) - Extracts detailed data + PCAP files 🆕 *Ready to use*

### What You Have

- ✅ **5,215 ANY.RUN report URLs** in `reports.xlsx`
- 🆕 **Complete scraping solution** ready to extract all data
- 🆕 **Analysis tools** for dataset exploration

---

## 📚 Documentation Quick Links

| Document | Purpose | When to Read |
|----------|---------|--------------|
| **[QUICK_START.md](QUICK_START.md)** | Simple step-by-step guide | **Start here** |
| **[SLOW_CONNECTION_GUIDE.md](SLOW_CONNECTION_GUIDE.md)** 🆕 | **Slow internet? Read this!** | **If pages load slowly** |
| **[SOLUTION_SUMMARY.md](SOLUTION_SUMMARY.md)** | Complete solution overview | Overview |
| **[SCRAPER_COMPARISON.md](SCRAPER_COMPARISON.md)** | Difference between scrapers | Understanding |
| **[FINAL_RECOMMENDATIONS.md](FINAL_RECOMMENDATIONS.md)** | Disk space & strategy | Before running |
| **[REPORT_SCRAPER_README.md](REPORT_SCRAPER_README.md)** | Detailed scraper docs | Reference |

---

## 🚀 Quick Start

### 1️⃣ Check Setup (30 seconds)
```powershell
python check_setup.py
```

### 2️⃣ Test with 3 URLs (5 minutes)
```powershell
python test_scraper.py
```

### 3️⃣ Run Full Scraper (5-8 hours)
```powershell
# Default settings (good for most connections)
python report_scraper.py --headless

# For slow connections (pages load slowly)
python report_scraper.py --timeout 120 --page-load-timeout 240 --headless
```
**📶 Slow connection?** See **[SLOW_CONNECTION_GUIDE.md](SLOW_CONNECTION_GUIDE.md)**

### 4️⃣ Analyze Results
```powershell
python analyze_dataset.py
```

**That's it!** 🎉

---

## 📦 What Gets Scraped

For each of the 5,215 reports:

### ✅ File Information
- File name, hashes (MD5, SHA1, SHA256, SSDEEP)
- Verdict (Malicious/Suspicious/Clean)
- Operating system, MIME type
- Tags (trojan, ransomware, etc.)

### ✅ Behavior Analysis
- Malicious behaviors
- Suspicious activities
- Process information

### ✅ MITRE ATT&CK Mappings
- Technique IDs (T1059, T1055, etc.)
- Technique names
- Tactics (Execution, Persistence, etc.)

### ✅ Network Data
- IP addresses and domains
- Ports and protocols
- Connection details

### ✅ PCAP Files
- Full network captures
- Labeled: `{task_id}_{verdict}_{filename}_{md5}.pcap`

---

## 📂 Repository Structure

```
d:\FYP\Scraper\
│
├── 📄 README.md                      # This file
├── 📄 QUICK_START.md                 # Step-by-step guide ⭐
├── 📄 SOLUTION_SUMMARY.md            # Complete overview
├── 📄 SCRAPER_COMPARISON.md          # Scraper differences
├── 📄 FINAL_RECOMMENDATIONS.md       # Disk space strategy
├── 📄 REPORT_SCRAPER_README.md       # Detailed docs
│
├── 🔧 requirements.txt               # Python dependencies
│
├── 🐍 any_run_scraper.py            # URL collector (done)
├── 🐍 report_scraper.py             # Report scraper (NEW)
├── 🐍 test_scraper.py               # Test with 3 URLs
├── 🐍 analyze_dataset.py            # Analysis utilities
├── 🐍 check_setup.py                # Pre-flight check
├── 🐍 create_subsets.py             # Create URL subsets
│
├── 📊 reports.xlsx                   # 5,215 URLs (INPUT)
│
├── 📁 scraped_data\                  # Output: JSON + CSV
│   ├── {task_id}_report.json
│   └── dataset_summary.csv
│
└── 📁 pcap_files\                    # Output: PCAP files
    └── {task_id}_{verdict}_{file}_{md5}.pcap
```

---

## 🛠️ Available Scripts

### Core Scripts

| Script | Purpose | Command |
|--------|---------|---------|
| `check_setup.py` | Verify setup | `python check_setup.py` |
| `test_scraper.py` | Test with 3 URLs | `python test_scraper.py` |
| `report_scraper.py` | Main scraper | `python report_scraper.py --headless` |
| `analyze_dataset.py` | Analyze results | `python analyze_dataset.py` |
| `create_subsets.py` | Create URL subsets | `python create_subsets.py subset --num 100` |

### URL Collector (Already Done)
| Script | Purpose | Status |
|--------|---------|--------|
| `any_run_scraper.py` | Collect URLs | ✅ Complete (5,215 URLs) |

---

## 💡 Common Use Cases

### Test Before Full Run
```powershell
python test_scraper.py
```

### Process Small Sample (100 URLs)
```powershell
python create_subsets.py subset --num 100
python report_scraper.py --input reports_100.xlsx --headless
```

### Process All Reports
```powershell
python report_scraper.py --headless
```

### Save PCAPs to External Drive
```powershell
python report_scraper.py --pcap-dir E:\PCAPs --headless
```

### Batch Processing (1000 URLs per batch)
```powershell
python create_subsets.py batch --size 1000
# Then process each batch file
```

### Analyze Results
```powershell
# Overall statistics
python analyze_dataset.py

# Specific report
python analyze_dataset.py --task-id 001fe2ea-a1ca-4f61-997a-a252bae8f3c0

# Export MITRE matrix
python analyze_dataset.py --mitre-matrix
```

---

## 📊 Output Format

### Individual Reports (JSON)
```json
{
  "task_id": "001fe2ea-a1ca-4f61-997a-a252bae8f3c0",
  "url": "https://app.any.run/tasks/...",
  "general_info": {...},
  "behavior_activities": [...],
  "mitre_attack": [
    {
      "technique_id": "T1059",
      "technique_name": "Command and Scripting Interpreter",
      "tactic": "Execution"
    }
  ],
  "network_data": [...],
  "process_info": [...],
  "static_info": {...},
  "pcap_file": "pcap_files/..."
}
```

### Summary Dataset (CSV)
| task_id | file_name | verdict | md5 | sha256 | num_behaviors | num_mitre_techniques | mitre_techniques | pcap_file |
|---------|-----------|---------|-----|--------|---------------|---------------------|------------------|-----------|
| 001fe... | malware.exe | Malicious | abc... | def... | 15 | 8 | T1059, T1055, ... | pcap_files/... |

---

## ⏱️ Time & Space Requirements

### For All 5,215 URLs

| Resource | Estimate |
|----------|----------|
| **Time** | 5-8 hours |
| **JSON files** | ~260 MB |
| **CSV** | ~2 MB |
| **PCAPs** | 25-100 GB |

### Recommended Disk Space
- **Minimum**: 30 GB
- **Comfortable**: 50 GB
- **Ideal**: 100 GB

---

## 🎓 Dataset Use Cases

Perfect for:
- 🤖 **Machine Learning**: Train malware classifiers
- 🎯 **MITRE ATT&CK**: Analyze technique patterns
- 🌐 **Network Analysis**: Study malware traffic
- 🔍 **Threat Intelligence**: Hash lookups and correlations
- 📊 **Research**: Malware behavior studies

---

## 🔧 Installation

```powershell
# Install dependencies
pip install -r requirements.txt

# Check setup
python check_setup.py
```

---

## 📖 Recommended Reading Order

1. **[QUICK_START.md](QUICK_START.md)** - Get started in 5 minutes
2. **[SCRAPER_COMPARISON.md](SCRAPER_COMPARISON.md)** - Understand the two scrapers
3. **[FINAL_RECOMMENDATIONS.md](FINAL_RECOMMENDATIONS.md)** - Disk space strategy
4. **[REPORT_SCRAPER_README.md](REPORT_SCRAPER_README.md)** - Detailed reference

---

## 🆘 Troubleshooting

### Issue: Not enough disk space
See **[FINAL_RECOMMENDATIONS.md](FINAL_RECOMMENDATIONS.md)** for strategies:
- Use external drive for PCAPs
- Batch processing
- Skip PCAPs initially

### Issue: Timeouts or errors
```powershell
# Increase delay between requests
python report_scraper.py --delay 5.0
```

### Issue: ChromeDriver problems
```powershell
pip install --upgrade undetected-chromedriver
```

### Issue: Want to resume
```powershell
# Just run again - automatically resumes
python report_scraper.py --headless
```

---

## 📞 Quick Reference

### Most Common Commands
```powershell
# Check everything is ready
python check_setup.py

# Test first
python test_scraper.py

# Run scraper
python report_scraper.py --headless

# Analyze
python analyze_dataset.py
```

### Create Subsets
```powershell
# 100 URLs
python create_subsets.py subset --num 100

# Batches of 500
python create_subsets.py batch --size 500

# Only malicious (after scraping)
python create_subsets.py malicious
```

---

## ✅ Pre-Flight Checklist

Before running the full scraper:

- [ ] Read **[QUICK_START.md](QUICK_START.md)**
- [ ] Ran `python check_setup.py`
- [ ] Tested with `python test_scraper.py`
- [ ] Reviewed test output
- [ ] Checked disk space (need 30-100 GB)
- [ ] Decided on PCAP storage location
- [ ] Ready for 5-8 hour run

---

## 🎯 Your Next Steps

### Step 1: Read Quick Start
```powershell
# Open in VS Code or browser
code QUICK_START.md
```

### Step 2: Check Setup
```powershell
python check_setup.py
```

### Step 3: Test
```powershell
python test_scraper.py
```

### Step 4: Run Full Scraper
```powershell
python report_scraper.py --headless
```

---

## 📈 What You'll Have After Scraping

- ✅ **5,215 detailed JSON reports** - Complete metadata
- ✅ **1 master CSV file** - Easy analysis
- ✅ **~5,000 PCAP files** - Network captures
- ✅ **MITRE ATT&CK mappings** - Technique IDs and tactics
- ✅ **Organized structure** - Ready for ML/research

---

## 🎉 Success Criteria

You'll know it worked when you have:

```
scraped_data/
  ├── 001fe2ea_report.json
  ├── 00249941_report.json
  ├── ... (5,215 files)
  └── dataset_summary.csv

pcap_files/
  ├── 001fe2ea_Malicious_sample_abc123.pcap
  ├── 00249941_Suspicious_file_def456.pcap
  └── ... (~5,000+ files)
```

Then analyze:
```powershell
python analyze_dataset.py
```

---

## 🚀 Ready to Start?

### Absolute Minimum Quick Start
```powershell
python test_scraper.py              # Test (5 min)
python report_scraper.py --headless # Run (5-8 hours)
python analyze_dataset.py           # Analyze
```

**Read [QUICK_START.md](QUICK_START.md) for detailed walkthrough!**

---

*Built for FYP - Malware Analysis Dataset Building*  
*Source: ANY.RUN Interactive Malware Sandbox*  
*Total Reports: 5,215*

This project provides a Python script that crawls the [ANY.RUN submissions](https://app.any.run/submissions) feed, collects the report links from each row in the history table, paginates through every page until the "Next" button is disabled, and exports the unique URLs to an Excel sheet.

> **Note:** The scraper assumes the public submissions feed is accessible without authentication. If ANY.RUN requires you to be signed in, log in to the service in the automated browser window before starting the script.

## Prerequisites

- Windows (tested on PowerShell with Python 3.12)
- Google Chrome installed (the script launches an undetected Chrome session automatically)
- Python virtual environment activated (the repo includes a `.venv` that was used during development)

## Installation

Install dependencies from the provided requirements file:

```powershell
D:/FYP/Scraper/.venv/Scripts/pip.exe install -r requirements.txt
```

## Usage

Run the scraper from the project root. By default it runs headless and writes `reports.xlsx` in the same directory. Provide the `--email` and `--password` options if your ANY.RUN account is required to view the submissions feed.

```powershell
D:/FYP/Scraper/.venv/Scripts/python.exe any_run_scraper.py
```

### Useful options

- `--output <path>` – override the Excel file destination (e.g. `--output data/report_links.xlsx`).
- `--no-headless` – open a visible Chrome window (useful for debugging or if authentication is required).
- `--timeout <seconds>` – adjust the explicit wait used for page elements (default: 20 seconds).
- `--state <path>` – change where the scraper writes its JSON checkpoint file (default: `scraper_state.json`).
- `--delay <seconds>` – pause between pages to respect rate limits (default: 1 second; set to 0 to disable).
- `--email` / `--password` – credentials for the automated login sequence.
- `--smtp-host/--smtp-port/--smtp-username/--smtp-password/--smtp-from/--smtp-to` – configure SMTP credentials used to send an email when a bot challenge pauses the scraper.
- `--smtp-no-tls` – opt out of STARTTLS if your SMTP server requires plain connections.
- `--bot-selector <css>` – override the CSS selector used to detect bot/anti-automation checks.
- `--bot-poll <seconds>` – change how frequently the scraper checks whether the bot challenge is cleared (default: 15 seconds).

Example with custom options:

```powershell
D:/FYP/Scraper/.venv/Scripts/python.exe any_run_scraper.py --no-headless --output data/reports.xlsx
```

The script will print the total number of report URLs that were collected and confirm where the Excel sheet was written.

## How it works

1. Launches a Chrome browser (headless by default) and opens the submissions page.
2. Performs an automated login (clicks `#sign-in-btn`, fills email/password, submits `#signIn`).
3. Waits for the `history-table--content-wrap` container to load.
4. Extracts all `<a>` elements inside rows with class `history-table--content__row` and stores unique `href` values.
5. Clicks the "Next" pagination button until it becomes disabled or disappears.
6. Saves (and keeps updating) the collected URLs in an Excel sheet with a single `report_url` column.
7. Records progress in a JSON state file so interrupted runs can resume from the next page automatically.

## Automatic resume and checkpoints

After each page is processed the scraper:

1. Writes the deduplicated URL list to the configured Excel file.
2. Updates the JSON state file with the collected URLs and the number of pages already processed.
3. Waits for the configured delay (default 1 second) before requesting the next page so you stay gentle on the site.
4. If a bot or anti-automation challenge is detected (using the configured selector), it pauses, optionally emails you using SMTP, and keeps polling until you complete the challenge in the browser.

## Email notifications for bot checks

To receive an email whenever a bot challenge interrupts the scrape, supply the SMTP options. At minimum you need `--smtp-host`, `--smtp-from`, and `--smtp-to`. If the SMTP server requires authentication, also provide `--smtp-username` and `--smtp-password` (the password can come from an app password or secret manager). By default the connection uses STARTTLS on port 587; pass `--smtp-no-tls` if your server expects a plain connection.

Example:

```powershell
D:/FYP/Scraper/.venv/Scripts/python.exe any_run_scraper.py `
	--smtp-host smtp.office365.com `
	--smtp-username user@example.com `
	--smtp-password "example-app-password" `
	--smtp-from user@example.com `
	--smtp-to security@example.com `
	--bot-poll 20
```

The scraper will email the listed recipients once per detected challenge event and continue to remind you in the console until the verification is cleared.

If the script is interrupted, the next launch will load this state, skip the pages that were already scraped, and continue where it left off. When it reaches the end of the feed it clears the state file so subsequent runs start fresh. Use the `--state` option if you want to store the checkpoint somewhere else (for example on a shared drive).

## Validation

A quick CLI help check was run to confirm the script parses options correctly:

```powershell
D:/FYP/Scraper/.venv/Scripts/python.exe any_run_scraper.py --help
```

This verifies the dependencies are installed and the script starts without import errors. A full end-to-end scrape requires accessing the live ANY.RUN site with network access.
