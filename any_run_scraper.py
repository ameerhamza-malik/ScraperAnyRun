"""Automated scraper for collecting report URLs from ANY.RUN submissions."""
from __future__ import annotations

import argparse
import json
import smtplib
import ssl
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from email.message import EmailMessage
from pathlib import Path
from typing import Iterable, List, Optional, Set

import pandas as pd
import random
import pyautogui
import undetected_chromedriver as uc
from selenium.common.exceptions import NoSuchElementException, TimeoutException, StaleElementReferenceException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


@dataclass
class ScraperConfig:
    base_url: str = "https://app.any.run/submissions"
    headless: bool = True
    wait_timeout: int = 20
    output_path: str = "reports.xlsx"
    state_path: str = "scraper_state.json"
    page_delay: float = 1.0
    smtp_host: Optional[str] = None
    smtp_port: int = 587
    smtp_username: Optional[str] = None
    smtp_password: Optional[str] = None
    smtp_from: Optional[str] = None
    smtp_to: Optional[str] = None
    smtp_use_tls: bool = True
    login_email: Optional[str] = None
    login_password: Optional[str] = None
    bot_check_selector: Optional[str] = (
        "form#challenge-form, div#cf-spinner, div[class*='cf-challenge'], "
        "div[class*='botcheck'], iframe[src*='challenge']"
    )
    bot_check_poll_interval: float = 15.0


class AnyRunScraper:
    def __init__(self, config: ScraperConfig) -> None:
        self.config = config
        self._driver: WebDriver | None = None
        self._wait: WebDriverWait | None = None
        self._collected_urls: Set[str] = set()
        self._state_path: Path | None = (
            Path(self.config.state_path).expanduser()
            if self.config.state_path
            else None
        )
        self._last_processed_date: Optional[str] = None
        self._current_scraping_date: Optional[datetime] = None
        self._bot_notified: bool = False
        self._load_state()

    # --- Driver management -------------------------------------------------
    def __enter__(self) -> "AnyRunScraper":
        self._start_driver()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.shutdown()

    def _start_driver(self) -> None:
        chrome_options = uc.ChromeOptions()
        if self.config.headless:
            chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1200")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")

        self._driver = uc.Chrome(options=chrome_options)
        self._wait = WebDriverWait(self._driver, self.config.wait_timeout)

    # --- State management -------------------------------------------------
    def _load_state(self) -> None:
        if self._state_path is None or not self._state_path.exists():
            return

        try:
            with self._state_path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"Warning: Unable to load state from {self._state_path}: {exc}")
            return

        urls = data.get("collected_urls", [])
        if isinstance(urls, list):
            self._collected_urls.update(
                str(url) for url in urls if isinstance(url, str)
            )
        
        last_date = data.get("last_processed_date")
        if isinstance(last_date, str) and last_date:
            self._last_processed_date = last_date
            # Parse the date to resume from
            try:
                self._current_scraping_date = datetime.strptime(last_date, "%d %B %Y, %H:%M").replace(hour=0, minute=0, second=0, microsecond=0)
            except:
                try:
                    self._current_scraping_date = datetime.strptime(last_date.split(',')[0], "%d %B %Y")
                except:
                    pass

        if self._collected_urls:
            print(
                f"Resuming with {len(self._collected_urls)} URLs collected."
            )
            if self._last_processed_date:
                print(f"Last processed date: {self._last_processed_date}")
            if self._current_scraping_date:
                print(f"Resuming from date: {self._current_scraping_date.strftime('%m/%d/%Y')}")

    def _save_state(self) -> None:
        if self._state_path is None:
            return

        state_data = {
            "collected_urls": sorted(self._collected_urls),
            "last_processed_date": self._last_processed_date,
            "current_scraping_date": self._current_scraping_date.strftime("%m/%d/%Y") if self._current_scraping_date else None,
            "timestamp": time.time(),
        }

        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            with self._state_path.open("w", encoding="utf-8") as handle:
                json.dump(state_data, handle, indent=2)
        except OSError as exc:
            print(f"Warning: Unable to write state to {self._state_path}: {exc}")

    def _clear_state(self) -> None:
        if self._state_path is None:
            return

        if not self._state_path.exists():
            return

        try:
            self._state_path.unlink()
        except OSError as exc:
            print(f"Warning: Unable to remove state file {self._state_path}: {exc}")

    def _persist_progress(self) -> None:
        urls = sorted(self._collected_urls)
        self._save_results(urls, final=False)
        self._save_state()

    def _apply_page_delay(self, reason: str) -> None:
        delay = getattr(self.config, "page_delay", 0.0)
        #random delay between 10 to 30 seconds
        delay = random.uniform(10, 30)
        if delay and delay > 0:
            print(f"{reason} Sleeping for {delay:.2f} second(s) to respect limits.")
            time.sleep(delay)

    @property
    def driver(self) -> WebDriver:
        if self._driver is None:
            raise RuntimeError("WebDriver has not been initialised")
        return self._driver

    @property
    def wait(self) -> WebDriverWait:
        if self._wait is None:
            raise RuntimeError("WebDriver wait has not been initialised")
        return self._wait

    def shutdown(self) -> None:
        if self._driver is not None:
            self._driver.quit()
            self._driver = None
            self._wait = None

    # --- Scraping logic ----------------------------------------------------
    def run(self) -> List[str]:
        self.driver.get(self.config.base_url)
        self._ensure_authenticated()
        self._ensure_table_loaded()
        
        # Start from current scraping date or today
        if self._current_scraping_date:
            current_date = self._current_scraping_date
            print(f"Resuming from: {current_date.strftime('%m/%d/%Y')}")
        else:
            current_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            print(f"Starting from today: {current_date.strftime('%m/%d/%Y')}")
        
        # Scrape day by day, going backwards
        while True:
            self._current_scraping_date = current_date
            date_str = current_date.strftime("%m/%d/%Y")
            
            print(f"\n{'='*60}")
            print(f"Scraping date: {date_str}")
            print(f"{'='*60}")
            
            # Apply date filter for this specific day
            if not self._apply_date_filter_for_day(date_str):
                print(f"Failed to apply date filter for {date_str}. Stopping.")
                break
            
            # Collect all URLs from this day (across all pages)
            page_count = 0
            while True:
                while self._handle_bot_challenge():
                    pass
                    
                page_count += 1
                print(f"  Processing page {page_count} for {date_str}...")
                
                urls_before = len(self._collected_urls)
                self._collect_current_page_urls()
                urls_collected = len(self._collected_urls) - urls_before
                print(f"    Collected {urls_collected} URLs from this page")
                
                self._persist_progress()
                self._apply_page_delay("Finished page")
                
                if not self._go_to_next_page():
                    print(f"  No more pages for {date_str}")
                    break
            
            print(f"Completed {date_str}. Total URLs collected: {len(self._collected_urls)}")
            
            # Move to previous day
            current_date = current_date - timedelta(days=1)
            print(f"\nMoving to previous day: {current_date.strftime('%m/%d/%Y')}")
        
        urls = sorted(self._collected_urls)
        self._save_results(urls, final=True)
        self._clear_state()
        return urls
    
    def _apply_date_filter_for_day(self, date_str: str) -> bool:
        """Apply date filter for a specific day (same date in both from and to fields)."""
        try:
            # Click filter button
            print(f"  Clicking filter button...")
            filter_button = self.wait.until(
                EC.element_to_be_clickable((By.ID, "history-filterBtn"))
            )
            filter_button.click()
            time.sleep(2)
            
            # Find the "From" date input field
            print(f"  Setting 'From' date to: {date_str}")
            date_from_input = self.wait.until(
                EC.presence_of_element_located((By.ID, "dateFrom"))
            )
            date_from_input.clear()
            date_from_input.send_keys(date_str)
            time.sleep(0.5)
            
            # Find the "To" date input field
            print(f"  Setting 'To' date to: {date_str}")
            date_to_input = self.wait.until(
                EC.presence_of_element_located((By.ID, "dateTo"))
            )
            date_to_input.clear()
            date_to_input.send_keys(date_str)
            time.sleep(1)
            
            # Click the Search button
            print(f"  Clicking Search button...")
            search_button = self.wait.until(
                EC.element_to_be_clickable((By.ID, "historySearchBtn"))
            )
            search_button.click()
            
            # Wait for table to reload
            time.sleep(3)
            self._ensure_table_loaded()
            
            print(f"  ✓ Date filter applied: {date_str}")
            return True
            
        except (NoSuchElementException, TimeoutException) as e:
            print(f"  ✗ Failed to apply date filter: {e}")
            return False

    def _ensure_table_loaded(self) -> None:
        while True:
            try:
                self.wait.until(
                    EC.presence_of_element_located(
                        (By.XPATH, "//*[contains(@class, 'history-table--content')]")
                    )
                )
            except TimeoutException:
                if self._handle_bot_challenge():
                    continue
                raise

            if self._handle_bot_challenge():
                continue
            return

    def _collect_current_page_urls(self) -> None:
        rows = self.driver.find_elements(By.CSS_SELECTOR, ".history-table--content__row")
        for row in rows:
            # Extract date from the row for verification and storage
            try:
                date_elem = row.find_element(By.CSS_SELECTOR, ".os__time")
                row_date = date_elem.text.strip()
                if row_date:
                    # Store the most recent date we've seen
                    self._last_processed_date = row_date
            except NoSuchElementException:
                pass
            
            for link in self._extract_links(row):
                href = link.get_attribute("href")
                if href and "/tasks" in href and "/browse" not in href:
                    self._collected_urls.add(href)

    def _extract_links(self, row: WebElement) -> Iterable[WebElement]:
        try:
            return row.find_elements(By.TAG_NAME, "a")
        except StaleElementReferenceException:
            return []

    def _go_to_next_page(self) -> bool:
        while self._handle_bot_challenge():
            pass
        try:
            next_button = self.wait.until(
                EC.element_to_be_clickable(
                    (
                        By.CSS_SELECTOR,
                        "button.history-pagination__next.history-pagination__button.history-pagination__element",
                    )
                )
            )
        except NoSuchElementException:
            return False

        if not self._is_button_enabled(next_button):
            return False

        self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", next_button)

        try:
            next_button.click()
        except StaleElementReferenceException:
            return False

        try:
            # self.wait.until(EC.staleness_of(next_button))
            self._ensure_table_loaded()
        except TimeoutException:
            return False

        time.sleep(0.5)
        return True

    def _is_button_enabled(self, button: WebElement) -> bool:
        disabled_attr = button.get_attribute("disabled")
        aria_disabled = button.get_attribute("aria-disabled")
        class_name = button.get_attribute("class") or ""
        return not (
            (disabled_attr is not None)
            or (aria_disabled and aria_disabled.lower() == "true")
            or ("disabled" in class_name.lower())
        )

    def _save_results(self, urls: List[str], *, final: bool) -> None:
        df = pd.DataFrame({"report_url": urls})
        if not urls:
            print("No URLs have been collected yet. The sheet will be empty.")
        df.to_excel(self.config.output_path, index=False)
        if final:
            print(f"Saved {len(urls)} report URLs to {self.config.output_path}")
        else:
            print(
                f"Progress saved: {len(urls)} URLs written to {self.config.output_path}"
            )

    def _handle_bot_challenge(self) -> bool:
        """Handle bot verification prompts using enhanced detection from scraper.py."""
        if not self._is_bot_challenge_present():
            if self._bot_notified:
                self._bot_notified = False
            return False

        if not self._bot_notified:
            self._notify_bot_block()

        print("\n  ⚠ Bot or captcha challenge detected.")
        print("    Attempting automated click to bypass...")
        time.sleep(2)
        
        # Automated click attempt using pyautogui
        self.click_on_bot_challenge()
        
        # Re-check if challenge is still present after automated click
        if self._is_bot_challenge_present():
            print("    ⚠ Challenge still detected after automated clicks.")
            print("    Please complete the verification manually in the browser.")
            time.sleep(self.config.bot_check_poll_interval)
        
        return True
    
    def _is_bot_challenge_present(self) -> bool:
        """Detect if a bot or captcha challenge overlay is visible (enhanced detection from scraper.py)."""
        if not self._driver:
            return False

        selectors = [
            (
                By.XPATH,
                "//*[contains(text(), 'We noticed a large number of requests') or contains(text(), 'We noticed large number of requests')]",
            ),
            (
                By.CSS_SELECTOR,
                "form#challenge-form, div#cf-spinner, div[class*='cf-challenge'], div[class*='botcheck']",
            ),
            (
                By.CSS_SELECTOR,
                "iframe[src*='challenge'], iframe[src*='turnstile'], iframe[id*='cf-chl'], iframe[title*='challenge']",
            ),
        ]

        # Check for "We noticed ... requests" message with case-insensitive search
        try:
            large_requests_present = any(
                el.is_displayed()
                for el in self.driver.find_elements(
                    By.XPATH, 
                    "//*[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'we noticed') and contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'requests')]"
                )
            )
            if large_requests_present:
                return True
        except Exception:
            # Fall back to normal selector checks below on any error
            pass

        # Check all other selectors
        for by, selector in selectors:
            try:
                elements = self.driver.find_elements(by, selector)
            except Exception:
                continue

            for element in elements:
                try:
                    if element.is_displayed():
                        return True
                except Exception:
                    continue

        return False

    def click_on_bot_challenge(self) -> None:
        """Click on the bot challenge using pyautogui."""
        print("\n  ⚠ Bot or captcha challenge detected.")
        print("    Attempting to click on the challenge using pyautogui.")

        try:
            time.sleep(2)  # Give some time to switch to the browser window
            x, y = 840, 660
            pyautogui.click(x, y)  # Click at specific coordinates
            print("    ▶ Clicked on the bot challenge. Waiting for verification...")
        except Exception as e:
            print(f"    ⚠ Failed to click on bot challenge: {e}")

    def _notify_bot_block(self) -> None:
        self._bot_notified = True
        if not self.config.smtp_host or not self.config.smtp_from or not self.config.smtp_to:
            print(
                "Bot challenge email notification skipped: SMTP host/from/to not fully configured."
            )
            return

        subject = "ANY.RUN scraper paused due to bot verification"
        body = (
            "Hello,\n\n"
            "The ANY.RUN scraper has encountered a bot/anti-automation challenge and is "
            "waiting for manual intervention. Please open the browser window, complete "
            "the verification, and the scraper will resume automatically.\n\n"
            "This message was generated automatically."
        )

        try:
            self._send_email_alert(subject, body)
            print("Bot challenge notification email sent.")
        except Exception as exc:
            print(f"Warning: Failed to send bot challenge notification email: {exc}")

    def _send_email_alert(self, subject: str, body: str) -> None:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = self.config.smtp_from

        recipients = [addr.strip() for addr in self.config.smtp_to.split(",") if addr.strip()]
        if not recipients:
            raise ValueError("No valid SMTP recipients resolved")
        msg["To"] = ", ".join(recipients)
        msg.set_content(body)

        context = ssl.create_default_context()
        if self.config.smtp_use_tls:
            with smtplib.SMTP(self.config.smtp_host, self.config.smtp_port, timeout=30) as server:
                server.ehlo()
                server.starttls(context=context)
                server.ehlo()
                if self.config.smtp_username and self.config.smtp_password:
                    server.login(self.config.smtp_username, self.config.smtp_password)
                server.send_message(msg, from_addr=self.config.smtp_from, to_addrs=recipients)
        else:
            with smtplib.SMTP(self.config.smtp_host, self.config.smtp_port, timeout=30) as server:
                if self.config.smtp_username and self.config.smtp_password:
                    server.login(self.config.smtp_username, self.config.smtp_password)
                server.send_message(msg, from_addr=self.config.smtp_from, to_addrs=recipients)

    def _is_table_visible(self, timeout: float = 5.0) -> bool:
        try:
            WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located(
                    (By.XPATH, "//*[contains(@class, 'history-table--content')]")
                )
            )
            return True
        except TimeoutException:
            return False

    def _ensure_authenticated(self) -> None:
        needs_login = False
        try:
            status_button = self.driver.find_element(By.CSS_SELECTOR, "button.status-bar__button")
            status_text = (status_button.text or "").strip().lower()
            if "guest" in status_text:
                needs_login = True
            elif "free" in status_text:
                return
        except NoSuchElementException:
            needs_login = not self._is_table_visible(timeout=3)

        if not needs_login:
            return

        if self.config.login_email and self.config.login_password:
            self._perform_login_via_ui()
            time.sleep(10)
        else:
            print(
                "No login credentials supplied; please sign in manually in the browser window before scraping continues."
            )

    def _perform_login_via_ui(self) -> None:
        email = self.config.login_email
        password = self.config.login_password
        if not email or not password:
            return

        print("Attempting automated login using provided credentials...")
        try:
            sign_in_button = self.wait.until(
                EC.element_to_be_clickable((By.ID, "sign-in-btn"))
            )
            sign_in_button.click()
        except TimeoutException:
            print("Sign-in button not found; attempting to locate login form directly.")

        try:
            email_field = self._wait_for_first_visible_element(
                [
                    (By.ID, "email"),
                    (By.NAME, "email"),
                    (By.CSS_SELECTOR, "input[type='email']"),
                ],
                "email input field",
            )
            password_field = self._wait_for_first_visible_element(
                [
                    (By.ID, "password"),
                    (By.NAME, "password"),
                    (By.CSS_SELECTOR, "input[type='password']"),
                ],
                "password input field",
            )

            email_field.clear()
            email_field.send_keys(email)
            password_field.clear()
            password_field.send_keys(password)

            submit_button = self._wait_for_first_clickable_element(
                [
                    (By.ID, "signIn"),
                    (By.CSS_SELECTOR, "button#signIn"),
                    (By.CSS_SELECTOR, "button[type='submit']"),
                ],
                "sign-in submit button",
            )
            submit_button.click()
        except TimeoutException as exc:
            print(
                "Login form elements could not be located automatically. "
                "If login is still required, please complete it manually in the browser window."
            )
            return

        if self._is_table_visible(timeout=self.config.wait_timeout):
            print("Login successful; proceeding with scraping.")
        else:
            print(
                "Warning: Table did not appear after login attempt. Please verify credentials or complete any additional verification manually."
            )

    def _wait_for_first_visible_element(self, selectors, description: str) -> WebElement:
        last_error: Optional[Exception] = None
        for by, value in selectors:
            try:
                return self.wait.until(EC.visibility_of_element_located((by, value)))
            except TimeoutException as exc:
                last_error = exc
        raise TimeoutException(f"Could not locate {description} using known selectors") from last_error

    def _wait_for_first_clickable_element(self, selectors, description: str) -> WebElement:
        last_error: Optional[Exception] = None
        for by, value in selectors:
            try:
                return self.wait.until(EC.element_to_be_clickable((by, value)))
            except TimeoutException as exc:
                last_error = exc
        raise TimeoutException(f"Could not locate {description} using known selectors") from last_error


# --- CLI -------------------------------------------------------------------

def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect ANY.RUN submission report URLs")
    parser.add_argument(
        "--output",
        default="reports.xlsx",
        help="Path to the Excel file where URLs will be stored",
    )
    parser.add_argument(
        "--headless",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Run browser in headless mode (default: enabled)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=20,
        help="Maximum wait time in seconds for page elements to appear",
    )
    parser.add_argument(
        "--state",
        default="scraper_state.json",
        help="Path to a JSON file used to persist scraping progress between runs",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=10.0,
        help="Seconds to wait between page requests (use 0 to disable)",
    )
    parser.add_argument(
        "--smtp-host",
        type=str,
        default="smtp.gmail.com",
        help="SMTP server hostname for email notifications",
    )
    parser.add_argument(
        "--smtp-port",
        type=int,
        default=587,
        help="SMTP server port (default: 587)",
    )
    parser.add_argument(
        "--smtp-username",
        type=str,
        default="malikameerhamzaqtb@gmail.com",
        help="SMTP username if authentication is required",
    )
    parser.add_argument(
        "--smtp-password",
        type=str,
        default="",
        help="SMTP password if authentication is required",
    )
    parser.add_argument(
        "--smtp-from",
        type=str,
        default="malikameerhamzaqtb@gmail.com",
        help="From address used when sending notification emails",
    )
    parser.add_argument(
        "--smtp-to",
        type=str,
        default="i221570@nu.edu.pk",
        help="Comma-separated list of recipients for notification emails",
    )
    parser.add_argument(
        "--smtp-no-tls",
        action="store_true",
        default=False,
        help="Disable STARTTLS when sending notification emails",
    )
    parser.add_argument(
        "--bot-selector",
        default=None,
        help="CSS selector(s) that indicate a bot challenge is present (comma-separated)",
    )
    parser.add_argument(
        "--bot-poll",
        type=float,
        default=15.0,
        help="Seconds to wait before re-checking for bot challenge resolution",
    )
    parser.add_argument(
        "--email",
        type=str,
        default="i221570@nu.edu.pk",
        help="Account email used for automatic login if cookies are not provided",
    )
    parser.add_argument(
        "--password",
        type=str,
        default="Ameerhamza@4",
        help="Account password used for automatic login if cookies are not provided",
    )
    return parser.parse_args(argv)


def main(argv: List[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    config = ScraperConfig(
        headless=args.headless,
        wait_timeout=args.timeout,
        output_path=args.output,
        state_path=args.state,
        page_delay=max(args.delay, 0.0),
        login_email=args.email,
        login_password=args.password,
    )

    # SMTP configuration
    if args.smtp_host:
        config.smtp_host = args.smtp_host
    if args.smtp_port:
        config.smtp_port = args.smtp_port
    if args.smtp_username:
        config.smtp_username = args.smtp_username
    if args.smtp_password:
        config.smtp_password = args.smtp_password
    if args.smtp_from:
        config.smtp_from = args.smtp_from
    if args.smtp_to:
        config.smtp_to = args.smtp_to
    config.smtp_use_tls = not args.smtp_no_tls

    # Bot detection configuration
    if args.bot_selector is not None:
        config.bot_check_selector = args.bot_selector
    if args.bot_poll is not None:
        config.bot_check_poll_interval = max(args.bot_poll, 1.0)

    with AnyRunScraper(config) as scraper:
        scraper.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
