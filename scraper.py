"""
Unified ANY.RUN Report Scraper
Complete scraping, analysis, and utility functions in one file.
"""

import json
import re
import time
import argparse
import sys
import smtplib
import ssl
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from collections import Counter
import pyautogui

import pandas as pd
import undetected_chromedriver as uc
from email.message import EmailMessage
from selenium.common.exceptions import (
    NoSuchElementException,
    TimeoutException,
    StaleElementReferenceException,
    ElementClickInterceptedException,
    WebDriverException,
)
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


# ============================================================================
# REPORT SCRAPER CLASS
# ============================================================================

class ReportScraper:
    """Scrapes detailed information from ANY.RUN sandbox reports."""

    def __init__(
        self,
        input_excel: str = "reports.xlsx",
        output_dir: str = "scraped_data",
        pcap_dir: str = "pcap_files",
        checkpoint_file: str = "scraper_checkpoint.json",
        headless: bool = False,
        wait_timeout: int = 60,
        page_delay: float = 2.0,
        page_load_timeout: int = 120,
        login_email: Optional[str] = None,
        login_password: Optional[str] = None,
        smtp_host: Optional[str] = None,
        smtp_port: int = 587,
        smtp_username: Optional[str] = None,
        smtp_password: Optional[str] = None,
        smtp_from: Optional[str] = None,
        smtp_to: Optional[str] = None,
        smtp_use_tls: bool = True,
    ):
        self.input_excel = input_excel
        self.output_dir = Path(output_dir)
        self.pcap_dir = Path(pcap_dir)
        self.checkpoint_file = Path(checkpoint_file)
        self.headless = headless
        self.wait_timeout = wait_timeout
        self.page_delay = page_delay
        self.page_load_timeout = page_load_timeout
        self.login_email = login_email
        self.login_password = login_password
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.smtp_username = smtp_username
        self.smtp_password = smtp_password
        self.smtp_from = smtp_from
        self.smtp_to = smtp_to
        self.smtp_use_tls = smtp_use_tls
        self.base_url = "https://app.any.run/"
        self._last_bot_prompt: float = 0.0
        self._bot_notification_sent = False

        # Create output directories
        self.output_dir.mkdir(exist_ok=True)
        self.pcap_dir.mkdir(exist_ok=True)

        # Load checkpoint
        self.processed_urls: Set[str] = self._load_checkpoint()

        # Initialize driver
        self.driver = None
        self.wait = None

    def _load_checkpoint(self) -> Set[str]:
        """Load processed URLs from checkpoint file."""
        if self.checkpoint_file.exists():
            try:
                with open(self.checkpoint_file, "r") as f:
                    data = json.load(f)
                    return set(data.get("processed_urls", []))
            except Exception as e:
                print(f"Warning: Could not load checkpoint: {e}")
        return set()

    def _save_checkpoint(self):
        """Save processed URLs to checkpoint file."""
        try:
            with open(self.checkpoint_file, "w") as f:
                json.dump(
                    {"processed_urls": list(self.processed_urls)},
                    f,
                    indent=2,
                )
        except Exception as e:
            print(f"Warning: Could not save checkpoint: {e}")

    def _init_driver(self):
        """Initialize the Chrome driver."""
        chrome_options = uc.ChromeOptions()
        if self.headless:
            chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1200")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        
        # Enable download
        prefs = {
            "download.default_directory": str(self.pcap_dir.absolute()),
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "safebrowsing.enabled": True,
        }
        chrome_options.add_experimental_option("prefs", prefs)

        self.driver = uc.Chrome(options=chrome_options)
        self.driver.set_page_load_timeout(self.page_load_timeout)
        self.wait = WebDriverWait(self.driver, self.wait_timeout)

    def _close_driver(self):
        """Close the Chrome driver."""
        if self.driver:
            self.driver.quit()
            self.driver = None
            self.wait = None

    def _extract_task_id(self, url: str) -> Optional[str]:
        """Extract task ID from URL."""
        match = re.search(r"/tasks/([a-f0-9-]+)", url)
        return match.group(1) if match else None

    def _wait_for_page_load(self, initial_wait: int = 5) -> bool:
        """Wait for page to fully load with multiple checks."""
        time.sleep(initial_wait)
        self._check_for_bot_challenge()
        
        # (By.CSS_SELECTOR, ".task-info"),
        #     (By.CSS_SELECTOR, ".report-content"),
        selectors_to_try = [
            (By.XPATH, "//div[contains(@class, 'task')]"),
            (By.TAG_NAME, "body"),
        ]
        
        for by, selector in selectors_to_try:
            try:
                print(f"    Waiting for element: {selector}...")
                self.wait.until(EC.presence_of_element_located((by, selector)))
                print(f"    ✓ Element found: {selector}")
                time.sleep(3)
                self._check_for_bot_challenge()
                
                try:
                    body_text = self.driver.find_element(By.TAG_NAME, "body").text
                    if len(body_text) > 100:
                        print(f"    ✓ Page content loaded ({len(body_text)} chars)")
                        return True
                except:
                    pass
            except TimeoutException:
                print(f"    ⏱ Timeout waiting for: {selector}")
                self._check_for_bot_challenge()
                continue
        
        print(f"    ⏳ Slow connection detected, waiting additional 10 seconds...")
        time.sleep(10)
        self._check_for_bot_challenge()
        
        try:
            body = self.driver.find_element(By.TAG_NAME, "body")
            if body and len(body.text) > 50:
                print(f"    ⚠ Proceeding with partial content")
                return True
        except:
            pass
        
        return False

    def _check_for_bot_challenge(self) -> bool:
        """Handle bot verification prompts and pause execution when required."""
        if not self.driver:
            return False

        try:
            self.driver.switch_to.default_content()
        except WebDriverException:
            pass

        if not self._is_bot_challenge_present():
            if self._bot_notification_sent:
                self._bot_notification_sent = False
            return False

        self._notify_bot_challenge()

        if time.time() - self._last_bot_prompt < 2.0:
            return True

        print("\n  ⚠ Bot or captcha challenge detected.")
        print("    Complete the verification manually in the browser window.")
        time.sleep(2)
        # automated click attempt
        self.click_on_bot_challenge()
        # # Check if the challenge is still present after click
        # if self._is_bot_challenge_present():
        #     self.click_on_bot_challenge()
        # if self._is_bot_challenge_present():
        #     self.click_on_bot_challenge()
        # if self._is_bot_challenge_present():
        #     self.click_on_bot_challenge()
        # if self._is_bot_challenge_present():
            # print("    ⚠ Challenge still detected after automated clicks.")
            # self._notify_bot_challenge()

        # Re-check whether the challenge persists after automated clicks.
        if self._is_bot_challenge_present():
            print("    ⚠ Challenge still detected after automated clicks.")
            self._notify_bot_challenge()
            try:
                input("    ▶ Press Enter after completing the verification: ")
            except EOFError:
                print("    ⚠ Unable to read input; continuing automatically.")
            self._last_bot_prompt = time.time()
            return True

        # If challenge cleared, update timestamp and continue.
        self._last_bot_prompt = time.time()
        return True
    def click_on_bot_challenge(self) -> None:
        """Click on the bot challenge using pyautogui."""
        print("\n  ⚠ Bot or captcha challenge detected.")
        print("    Attempting to click on the challenge using pyautogui.")

        try:
            time.sleep(2)  # Give some time to switch to the browser window
            x, y = 840,660
            pyautogui.click(x,y)  # Click in the center of the screen
            print("    ▶ Clicked on the bot challenge. Please complete the verification.")
        except Exception as e:
            print(f"    ⚠ Failed to click on bot challenge: {e}")
    def _is_bot_challenge_present(self) -> bool:
        """Detect if a bot or captcha challenge overlay is visible."""
        if not self.driver:
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

        # Require the presence of both messages ("Suspicious activity" AND "We noticed ... requests")
        try:
            large_requests_present = any(
            el.is_displayed()
            for el in self.driver.find_elements(By.XPATH, "//*[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'we noticed') and contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'requests')]")
            )
            if large_requests_present:
                return True
        except Exception:
            # Fall back to normal selector checks below on any error
            pass

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

    def _notify_bot_challenge(self) -> None:
        """Send a single email notification when manual captcha action is required."""
        if self._bot_notification_sent:
            return

        if not self.smtp_host or not self.smtp_from or not self.smtp_to:
            return

        subject = "ANY.RUN scraper paused due to bot verification"
        body = (
            "Hello,\n\n"
            "The ANY.RUN report scraper has encountered a bot or captcha challenge "
            "and requires manual verification. Please open the automation browser "
            "window, complete the verification, and then return here to resume.\n\n"
            f"Current URL: {self.driver.current_url if self.driver else 'unknown'}\n\n"
            "This notification will not repeat until the challenge is cleared."
        )

        try:
            self._send_email_notification(subject, body)
            print("    ✉ Bot challenge notification email sent.")
        except Exception as exc:
            print(f"    ⚠ Failed to send bot challenge email notification: {exc}")
        finally:
            self._bot_notification_sent = True

    def _send_email_notification(self, subject: str, body: str) -> None:
        """Send an email message using configured SMTP credentials."""
        if not self.smtp_host or not self.smtp_from or not self.smtp_to:
            raise ValueError("SMTP host, from, and to addresses must be configured")

        recipients = [addr.strip() for addr in self.smtp_to.split(",") if addr.strip()]
        if not recipients:
            raise ValueError("No valid SMTP recipients resolved")

        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = self.smtp_from
        msg["To"] = ", ".join(recipients)
        msg.set_content(body)

        context = ssl.create_default_context()
        with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=30) as server:
            if self.smtp_use_tls:
                server.ehlo()
                server.starttls(context=context)
                server.ehlo()
            if self.smtp_username and self.smtp_password:
                server.login(self.smtp_username, self.smtp_password)
            server.send_message(msg, from_addr=self.smtp_from, to_addrs=recipients)

    def _safe_find_text(self, element: WebElement, selector: str, default: str = "") -> str:
        """Safely find and extract text from an element."""
        try:
            found = element.find_element(By.CSS_SELECTOR, selector)
            return found.text.strip()
        except NoSuchElementException:
            return default

    def _safe_find_elements(self, element: WebElement, selector: str) -> List[WebElement]:
        """Safely find multiple elements."""
        try:
            return element.find_elements(By.CSS_SELECTOR, selector)
        except Exception:
            return []

    def _initial_login(self):
        """Perform an initial login if credentials are provided."""
        if not self.login_email or not self.login_password:
            return

        try:
            print("  Checking login status...")
            self.driver.get(self.base_url)
            time.sleep(2)
            self._handle_login_if_needed()
        except Exception as exc:
            print(f"  Warning: initial login attempt failed ({exc})")

    def _handle_login_if_needed(self, target_url: Optional[str] = None):
        """Login when redirected or prompted."""
        if not self.login_email or not self.login_password:
            return

        time.sleep(1)
        current_url = self.driver.current_url.lower()
        if "login" in current_url or "sign-in" in current_url:
            self._perform_login_via_ui()
            if target_url:
                time.sleep(2)
                self.driver.get(target_url)
            return

        try:
            sign_in_button = self.driver.find_element(By.ID, "sign-in-btn")
            if sign_in_button.is_displayed():
                sign_in_button.click()
                time.sleep(1)
                self._perform_login_via_ui()
                if target_url:
                    time.sleep(2)
                    self.driver.get(target_url)
                return
        except NoSuchElementException:
            pass

        try:
            self.driver.find_element(By.CSS_SELECTOR, "input[type='email']")
            self._perform_login_via_ui()
            if target_url:
                time.sleep(2)
                self.driver.get(target_url)
        except NoSuchElementException:
            if not self._is_logged_in():
                print("  Login may be required; please sign in manually if prompted.")

    def _is_logged_in(self) -> bool:
        """Check if the current session appears authenticated."""
        try:
            status_button = self.driver.find_element(By.CSS_SELECTOR, "button.status-bar__button")
            status_text = (status_button.text or "").strip().lower()
            return "guest" not in status_text and "sign in" not in status_text
        except NoSuchElementException:
            return "login" not in self.driver.current_url.lower()

    def _perform_login_via_ui(self):
        """Fill in login form using provided credentials."""
        email = self.login_email
        password = self.login_password
        if not email or not password:
            return

        print("  Attempting login with provided credentials...")
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
            time.sleep(5)

        except TimeoutException:
            print("  Login form not detected automatically; complete login manually.")
            return

        if self._is_logged_in():
            print("  ✓ Login successful")
        else:
            print("  ⚠ Unable to confirm login; verify manually in the browser.")

    def _wait_for_first_visible_element(self, selectors, description: str) -> WebElement:
        last_error = None
        for by, value in selectors:
            try:
                return self.wait.until(EC.visibility_of_element_located((by, value)))
            except TimeoutException as exc:
                last_error = exc
        raise TimeoutException(f"Could not locate {description}") from last_error

    def _wait_for_first_clickable_element(self, selectors, description: str) -> WebElement:
        last_error = None
        for by, value in selectors:
            try:
                return self.wait.until(EC.element_to_be_clickable((by, value)))
            except TimeoutException as exc:
                last_error = exc
        raise TimeoutException(f"Could not locate {description}") from last_error

    def _hover_and_get_tooltip(self, element: Optional[WebElement], hover_pause: float = 0.2) -> str:
        """Hover over an element and return the visible tooltip text if present."""
        if element is None:
            return ""

        tooltip_text = ""
        try:
            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
        except Exception:
            pass

        try:
            ActionChains(self.driver).move_to_element(element).pause(hover_pause).perform()
            tooltip_candidates = WebDriverWait(self.driver, 2).until(
                lambda d: [el for el in d.find_elements(By.CSS_SELECTOR, "div.tooltip-inner") if el.is_displayed()]
            )
            if tooltip_candidates:
                tooltip_text = tooltip_candidates[-1].text.strip()
        except Exception:
            pass

        return tooltip_text

    def scrape_general_info(self) -> Dict:
        """Scrape general information section."""
        info: Dict[str, Any] = {}

        try:
            try:
                name_elem = self.driver.find_element(
                    By.CSS_SELECTOR, "[data-sm-id='info-block-os-task-name']"
                )
                name_text = name_elem.text.strip()
                if name_text:
                    info["file_name"] = name_text
                    info["task_name"] = name_text
            except NoSuchElementException:
                try:
                    fallback_name = self.driver.find_element(
                        By.CSS_SELECTOR, "h1.task-info__header, .task-info__filename"
                    )
                    info["file_name"] = fallback_name.text.strip()
                except NoSuchElementException:
                    info["file_name"] = ""

            try:
                verdict_elem = self.driver.find_element(
                    By.CSS_SELECTOR, "span.info-block-verdict__text"
                )
                info["verdict"] = verdict_elem.text.strip()
            except NoSuchElementException:
                try:
                    fallback_verdict = self.driver.find_element(
                        By.CSS_SELECTOR, ".verdict-block__verdict, .verdict"
                    )
                    info["verdict"] = fallback_verdict.text.strip()
                except NoSuchElementException:
                    info["verdict"] = ""

            try:
                os_elem = self.driver.find_element(
                    By.CSS_SELECTOR, ".info-block-os-logo__name"
                )
                info["os"] = os_elem.text.strip()
            except NoSuchElementException:
                try:
                    fallback_os = self.driver.find_element(
                        By.XPATH, "//div[contains(text(), 'OS:')]//following-sibling::div"
                    )
                    info["os"] = fallback_os.text.strip()
                except NoSuchElementException:
                    info["os"] = ""

            hash_row_selectors = {
                "md5": ".info-block-os-task-description__row-md5",
                "sha1": ".info-block-os-task-description__row-sha1",
                "sha256": ".info-block-os-task-description__row-sha256",
            }

            for hash_key, selector in hash_row_selectors.items():
                try:
                    row_elem = self.driver.find_element(By.CSS_SELECTOR, selector)
                    span_values = [
                        span.text.strip()
                        for span in row_elem.find_elements(By.TAG_NAME, "span")
                        if span.text.strip()
                    ]
                    if span_values:
                        info[hash_key] = " ".join(span_values)
                    else:
                        row_text = row_elem.text.strip()
                        if row_text:
                            info[hash_key] = row_text
                except NoSuchElementException:
                    info.setdefault(hash_key, "")

            legacy_hash_map = {
                "md5": "MD5",
                "sha1": "SHA1",
                "sha256": "SHA256",
                "ssdeep": "SSDEEP",
            }
            for hash_key, label in legacy_hash_map.items():
                if info.get(hash_key):
                    continue
                try:
                    hash_elem = self.driver.find_element(
                        By.XPATH,
                        f"//div[contains(text(), '{label}')]//following-sibling::div | "
                        f"//span[contains(text(), '{label}')]//following-sibling::span"
                    )
                    info[hash_key] = hash_elem.text.strip()
                except NoSuchElementException:
                    info.setdefault(hash_key, "")

            try:
                mime_elem = self.driver.find_element(
                    By.XPATH, "//div[contains(text(), 'MIME')]//following-sibling::div"
                )
                info["mime_type"] = mime_elem.text.strip()
            except NoSuchElementException:
                info.setdefault("mime_type", "")

            try:
                tags_container = self.driver.find_element(By.CSS_SELECTOR, ".info-block-os-tags")
                tags = [
                    link.text.strip()
                    for link in tags_container.find_elements(By.TAG_NAME, "a")
                    if link.text.strip()
                ]
                info["tags"] = tags
            except NoSuchElementException:
                try:
                    legacy_tags = self.driver.find_elements(By.CSS_SELECTOR, ".tag, .task-tag")
                    info["tags"] = [tag.text.strip() for tag in legacy_tags if tag.text.strip()]
                except Exception:
                    info["tags"] = []

            try:
                tracker_container = self.driver.find_element(By.CSS_SELECTOR, ".info-block-tracker__list")
                tracker_entries: List[Dict[str, str]] = []
                for link in tracker_container.find_elements(By.CSS_SELECTOR, "a.info-block-tracker__list-item"):
                    label = link.text.replace(",", " ").strip()
                    href = link.get_attribute("href") or ""
                    tooltip = (link.get_attribute("data-original-title") or "").strip()
                    entry: Dict[str, str] = {}
                    if label:
                        entry["label"] = " ".join(label.split())
                    if href:
                        entry["url"] = href
                    if tooltip and tooltip.lower() != "null":
                        entry["tooltip"] = tooltip
                    if entry:
                        tracker_entries.append(entry)
                info["trackers"] = tracker_entries
            except NoSuchElementException:
                info.setdefault("trackers", [])

            try:
                indicator_container = self.driver.find_element(
                    By.CSS_SELECTOR, ".info-block-indicators__list"
                )
                indicator_entries: List[Dict[str, str]] = []
                for item in indicator_container.find_elements(By.TAG_NAME, "li"):
                    entry: Dict[str, str] = {}
                    label_text = item.text.strip()
                    if label_text:
                        entry["label"] = label_text
                    tooltip_text = self._hover_and_get_tooltip(item)
                    if tooltip_text:
                        entry["tooltip"] = tooltip_text
                    if entry:
                        indicator_entries.append(entry)
                info["indicators"] = indicator_entries
                info["indicators_count"] = str(len(indicator_entries)) if indicator_entries else "0"
            except NoSuchElementException:
                info.setdefault("indicators", [])
                # fall back to older indicator count element if available
                try:
                    indicator_count_elem = self.driver.find_element(
                        By.XPATH, "//div[contains(text(), 'Indicators')]//following-sibling::div"
                    )
                    info["indicators_count"] = indicator_count_elem.text.strip()
                except NoSuchElementException:
                    info.setdefault("indicators_count", "")

        except Exception as e:
            print(f"Error extracting general info: {e}")

        return info

    def scrape_ioc_details(self) -> Dict[str, Any]:
        """Scrape IOC details via modal copy action."""
        result: Dict[str, Any] = {"raw_text": "", "main_object": None, "sections": {}}
        modal = None

        try:
            open_button = self.wait.until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "[data-sm-id='info-block-options-ioc']"))
            )
            open_button.click()
        except TimeoutException:
            return result
        except Exception as exc:
            print(f"  ⚠ Unable to open IOC modal: {exc}")
            return result

        try:
            modal = self.wait.until(
                EC.visibility_of_element_located((By.CSS_SELECTOR, ".iocModal, .ioc-modal, .sm-modal"))
            )
        except TimeoutException:
            print("  ⚠ IOC modal did not appear after clicking button")
            return result

        try:
            WebDriverWait(self.driver, min(self.wait_timeout, 10)).until(
                lambda d: modal.find_elements(By.CSS_SELECTOR, ".iocModal__main-category")
            )
        except TimeoutException:
            pass

        try:
            parsed = self._parse_ioc_modal_content(modal)
            result.update({k: v for k, v in parsed.items() if v is not None})
        except Exception as exc:
            print(f"  ⚠ Error parsing IOC modal content: {exc}")

        try:
            close_candidates = modal.find_elements(
                By.CSS_SELECTOR,
                "button[aria-label='Close'], .modal__close, .sm-modal__close, .iocModal__close, .infoBlockModal__header-closeBtn, button.infoBlockModal__header-closeBtn"
            )
            for button in close_candidates:
                if button.is_displayed():
                    try:
                        button.click()
                        break
                    except Exception:
                        continue
            else:
                try:
                    ActionChains(self.driver).send_keys(Keys.ESCAPE).perform()
                except Exception:
                    pass
        except Exception:
            pass

        return result

    def _parse_ioc_modal_content(self, modal: WebElement) -> Dict[str, Any]:
        """Parse IOC modal content directly from DOM into structured data."""
        parsed: Dict[str, Any] = {
            "main_object": None,
            "sections": {},
        }

        try:
            total_count_elem = modal.find_element(By.CSS_SELECTOR, ".iocModal__header-totalCount")
            total_count_text = total_count_elem.text.strip()
            if total_count_text:
                parsed["total_count"] = total_count_text
        except NoSuchElementException:
            parsed["total_count"] = None

        try:
            categories = modal.find_elements(By.CSS_SELECTOR, ".iocModal__main-category")
        except NoSuchElementException:
            categories = []

        seen_keys: Set[str] = set()

        for idx, category in enumerate(categories, start=1):
            caption_elem: Optional[WebElement] = None
            try:
                caption_elem = category.find_element(By.CSS_SELECTOR, ".iocCategory__caption")
                caption_text = caption_elem.text.strip()
            except NoSuchElementException:
                caption_text = f"Section {idx}"

            amount_text = ""
            try:
                amount_elem = category.find_element(By.CSS_SELECTOR, ".iocCategory__caption-amount")
                amount_text = amount_elem.text.strip()
                if amount_text.startswith("(") and amount_text.endswith(")"):
                    amount_text = amount_text[1:-1].strip()
            except NoSuchElementException:
                pass

            caption_class = caption_elem.get_attribute("class") if caption_elem else ""
            is_main_object = "iocCategory__caption--main" in (caption_class or "")
            main_name = ""
            if is_main_object:
                try:
                    name_elem = category.find_element(By.CSS_SELECTOR, ".iocCategory__caption-iocName")
                    main_name = name_elem.text.strip()
                except NoSuchElementException:
                    main_name = ""

            entries: List[Dict[str, Any]] = []
            list_items = category.find_elements(By.CSS_SELECTOR, "li.iocCategoryList-item")

            for item in list_items:
                entry: Dict[str, Any] = {}

                # Extract reputation text or icon tooltip
                try:
                    rep_container = item.find_element(By.CSS_SELECTOR, ".iocTextWrapper__reputation")
                    rep_text = rep_container.text.strip()
                    if not rep_text:
                        tooltip_spans = rep_container.find_elements(By.CSS_SELECTOR, ".tooltip-wrapper__tooltip-text")
                        if tooltip_spans:
                            rep_text = tooltip_spans[-1].text.strip()
                    if rep_text:
                        entry["reputation"] = rep_text
                    try:
                        rep_icon = rep_container.find_element(By.TAG_NAME, "use")
                        icon_ref = (rep_icon.get_attribute("xlink:href") or rep_icon.get_attribute("href") or "").strip()
                        if icon_ref:
                            entry["reputation_icon"] = icon_ref.lstrip("#")
                    except NoSuchElementException:
                        pass
                except NoSuchElementException:
                    pass

                try:
                    type_elem = item.find_element(By.CSS_SELECTOR, ".iocTextWrapperItem__item--type")
                    type_text = type_elem.text.strip()
                    if type_text:
                        entry["type"] = type_text
                except NoSuchElementException:
                    pass

                values_container = None
                try:
                    values_container = item.find_element(By.CSS_SELECTOR, ".iocTextWrapperItem__item--ioc")
                except NoSuchElementException:
                    pass

                value_groups: List[Dict[str, Any]] = []
                flattened_values: List[str] = []

                if values_container is not None:
                    group_elements = values_container.find_elements(
                        By.CSS_SELECTOR,
                        ".iocTextWrapperItem__item-hashName, .iocTextWrapperItem__item-hashIoc, .iocTextWrapperItem__item-noHash",
                    )

                    if not group_elements:
                        group_elements = [values_container]

                    for group in group_elements:
                        group_class = group.get_attribute("class") or ""
                        label = "value"
                        if "hashName" in group_class:
                            label = "path"
                        elif "hashIoc" in group_class:
                            label = "hash"

                        texts = [
                            span.text.strip()
                            for span in group.find_elements(By.CSS_SELECTOR, ".iocTextWrapperItem__item-span")
                            if span.text.strip()
                        ]
                        if not texts:
                            block_text = group.text.strip()
                            if block_text:
                                texts = [block_text]

                        if texts:
                            flattened_values.extend(texts)
                            value_groups.append({"label": label, "values": texts})

                if flattened_values:
                    unique_values = []
                    for value in flattened_values:
                        if value not in unique_values:
                            unique_values.append(value)
                    entry["values"] = unique_values
                elif values_container is not None:
                    container_text = values_container.text.strip()
                    if container_text:
                        entry["values"] = [container_text]

                if value_groups:
                    entry["value_groups"] = value_groups

                if entry:
                    entries.append(entry)

            if is_main_object:
                parsed["main_object"] = {
                    "title": caption_text or "Main object",
                    "name": main_name,
                    "attributes": entries,
                }
            else:
                key = re.sub(r"[^a-z0-9]+", "_", (caption_text or f"section_{idx}").lower()).strip("_")
                if not key:
                    key = f"section_{idx}"
                original_key = key
                suffix = 1
                while key in seen_keys:
                    suffix += 1
                    key = f"{original_key}_{suffix}"
                seen_keys.add(key)

                parsed["sections"][key] = {
                    "title": caption_text,
                    "count": amount_text,
                    "items": entries,
                }

        return parsed

    def scrape_behavior_activities(self) -> List[Dict]:
        """Scrape behavior activities."""
        activities = []
        
        try:
            behavior_elements = self.driver.find_elements(
                By.CSS_SELECTOR, ".behavior-item, .activity-item, [class*='behavior']"
            )
            
            for elem in behavior_elements:
                try:
                    activity = {}
                    
                    try:
                        severity_elem = elem.find_element(
                            By.CSS_SELECTOR, ".severity, .category, [class*='malicious'], [class*='suspicious']"
                        )
                        activity["severity"] = severity_elem.text.strip()
                    except NoSuchElementException:
                        activity["severity"] = ""
                    
                    activity["description"] = elem.text.strip()
                    
                    try:
                        process_elem = elem.find_element(By.CSS_SELECTOR, ".process-name, [class*='process']")
                        activity["process"] = process_elem.text.strip()
                    except NoSuchElementException:
                        activity["process"] = ""
                    
                    if activity["description"]:
                        activities.append(activity)
                        
                except Exception:
                    continue
                    
        except Exception as e:
            print(f"Error extracting behavior activities: {e}")

        return activities

    def scrape_mitre_attack(self) -> Dict[str, Any]:
        """Scrape MITRE ATT&CK mappings and related categorization."""
        mitre_result: Dict[str, Any] = {"techniques": [], "categorization": []}
        
        try:
            try:
                mitre_open_button = self.driver.find_element(
                    By.XPATH,
                    "//button[@data-sm-id='info-block-options-mitre' and contains(normalize-space(.), 'ATT')]"
                )
                mitre_open_button.click()
            except NoSuchElementException:
                pass
            time.sleep(3)
            matrix_wait_timeout = max(10, min(self.wait_timeout, 45))
            try:
                WebDriverWait(self.driver, matrix_wait_timeout).until(
                    EC.presence_of_element_located(
                        (By.CSS_SELECTOR, ".mitreMatrix__main-listWrapper")
                    )
                )
                WebDriverWait(self.driver, matrix_wait_timeout).until(
                    lambda d: bool(
                        d.find_elements(By.CSS_SELECTOR, ".main-mitre-list__item")
                    )
                )
            except TimeoutException:
                print("  ⚠ MITRE ATT&CK matrix still loading after wait timeout.")
                # Give the UI a final short grace period before attempting extraction
                time.sleep(3)

            tactic_sequence = [
                "Initial Access",
                "Execution",
                "Persistence",
                "Privilege Escalation",
                "Defense Evasion",
                "Credential Access",
                "Discovery",
                "Lateral Movement",
                "Collection",
                "Command and Control",
                "Exfiltration",
                "Impact",
            ]
            # Ensure MITRE matrix wrapper exists; if not, no MITRE info is available
            try:
                wrappers = self.driver.find_elements(
                    By.CSS_SELECTOR,
                    ".mitreMatrix__main-listWrapper.webkit-enabled-mitreMatrix"
                )
                # Fallback to a more generic wrapper class if exact compound class isn't present
                if not wrappers:
                    wrappers = self.driver.find_elements(By.CSS_SELECTOR, ".mitreMatrix__main-listWrapper")
                if not wrappers:
                    print("  ⚠ MITRE ATT&CK matrix not present on page. Skipping MITRE extraction.")
                    return mitre_result
            except Exception as e:
                print(f"  ⚠ Error checking for MITRE matrix presence: {e}")
                return mitre_result
            # Collect categorization list (only once for the page)
            categorization_items = self.driver.find_elements(
                By.CSS_SELECTOR, ".categorization-list__item"
            )
            for cat_item in categorization_items:
                try:
                    name_elem = cat_item.find_element(
                        By.CSS_SELECTOR, ".categorization-list__item-name"
                    )
                    amount_elem = cat_item.find_element(
                        By.CSS_SELECTOR, ".categorization-list__item-amount"
                    )
                    entry = {
                        "name": name_elem.text.strip(),
                        "amount": amount_elem.text.strip(),
                    }
                    if entry["name"] or entry["amount"]:
                        mitre_result.setdefault("categorization", []).append(entry)
                except NoSuchElementException:
                    continue

            tactic_elements = self.driver.find_elements(By.CSS_SELECTOR, ".main-mitre-list__item")

            if tactic_elements:
                for index, tactic_elem in enumerate(tactic_elements):
                    tactic_name = tactic_sequence[index] if index < len(tactic_sequence) else f"Tactic {index + 1}"

                    column_items = tactic_elem.find_elements(By.CSS_SELECTOR, ".main-columsList__item")
                    for col_item in column_items:
                        try:
                            technique: Dict[str, Any] = {"tactic": tactic_name}

                            # Technique title
                            try:
                                title_elem = col_item.find_element(
                                    By.CSS_SELECTOR, ".mitre-technic-item__title"
                                )
                                technique_name = title_elem.text.strip()
                                if technique_name:
                                    technique["technique_name"] = technique_name
                            except NoSuchElementException:
                                pass

                            # Technique ID (if available)
                            try:
                                id_elem = col_item.find_element(
                                    By.CSS_SELECTOR, ".mitre-info__technique"
                                )
                                technique_id = id_elem.text.strip()
                                if technique_id:
                                    technique["technique_id"] = technique_id
                            except NoSuchElementException:
                                # Sometimes the ID might be part of button text
                                try:
                                    possible_id = col_item.text
                                    match = re.search(r"T\d{4}(?:\.\d{3})?", possible_id)
                                    if match:
                                        technique["technique_id"] = match.group(0)
                                except Exception:
                                    pass

                            # Traffic light / severity indicator
                            try:
                                indicator_elem = col_item.find_element(
                                    By.CSS_SELECTOR, ".mitre-trafficLight-list__item"
                                )
                                indicator_text = indicator_elem.text.strip()
                                if indicator_text:
                                    technique["indicator_count"] = indicator_text
                                
                            except NoSuchElementException:
                                pass

                            # Collect any additional descriptive text
                            body_text = col_item.text.strip()
                            if body_text:
                                technique["raw_text"] = body_text

                            if any(
                                key in technique
                                for key in ("technique_name", "technique_id", "indicator_count")
                            ):
                                mitre_result["techniques"].append(technique)

                        except Exception:
                            continue

            else:
                # Fallback to previous generic scraping logic
                technique_elements = self.driver.find_elements(
                    By.CSS_SELECTOR, ".mitre-technique, .technique-item, [class*='mitre']"
                )

                for elem in technique_elements:
                    try:
                        technique: Dict[str, Any] = {}

                        try:
                            id_elem = elem.find_element(By.CSS_SELECTOR, ".technique-id, [class*='id']")
                            technique_id = id_elem.text.strip()
                            if technique_id:
                                technique["technique_id"] = technique_id
                        except NoSuchElementException:
                            text = elem.text
                            match = re.search(r"T\d{4}(?:\.\d{3})?", text)
                            if match:
                                technique["technique_id"] = match.group(0)

                        try:
                            name_elem = elem.find_element(By.CSS_SELECTOR, ".technique-name, [class*='name']")
                            technique_name = name_elem.text.strip()
                            if technique_name:
                                technique["technique_name"] = technique_name
                        except NoSuchElementException:
                            text = elem.text.strip()
                            if text:
                                technique["technique_name"] = text

                        try:
                            tactic_elem = elem.find_element(By.CSS_SELECTOR, ".tactic, [class*='tactic']")
                            tactic_name = tactic_elem.text.strip()
                            if tactic_name:
                                technique["tactic"] = tactic_name
                        except NoSuchElementException:
                            pass

                        if technique:
                            mitre_result["techniques"].append(technique)

                    except Exception:
                        continue

        except Exception as e:
            print(f"Error extracting MITRE ATT&CK data: {e}")
        finally:
            try:
                close_button = self.driver.find_element(
                    By.XPATH, "//button[contains(@class, 'mitreMatrix__header-closeBtn')]"
                )
                close_button.click()
                time.sleep(1)
            except NoSuchElementException:
                pass

        return mitre_result

    def scrape_network_data(self) -> List[Dict]:
        """Scrape network connection data."""
        network_data = []
        
        try:
            try:
                network_tab = self.driver.find_element(
                    By.XPATH, "//button[contains(text(), 'Network') or contains(@class, 'network')]"
                )
                network_tab.click()
                time.sleep(2)
            except NoSuchElementException:
                pass
            
            connection_elements = self.driver.find_elements(
                By.CSS_SELECTOR, ".connection-item, .network-connection, [class*='connection']"
            )
            
            for elem in connection_elements:
                try:
                    connection = {}
                    text = elem.text.strip()
                    
                    ip_pattern = r"\b(?:\d{1,3}\.){3}\d{1,3}\b"
                    ips = re.findall(ip_pattern, text)
                    if ips:
                        connection["ip"] = ips[0] if len(ips) == 1 else ips
                    
                    domain_pattern = r"[a-zA-Z0-9-]+\.[a-zA-Z]{2,}"
                    domains = re.findall(domain_pattern, text)
                    if domains:
                        connection["domain"] = domains[0]
                    
                    port_pattern = r":(\d+)"
                    ports = re.findall(port_pattern, text)
                    if ports:
                        connection["port"] = ports[0]
                    
                    connection["raw_data"] = text
                    
                    if connection:
                        network_data.append(connection)
                        
                except Exception:
                    continue
                    
        except Exception as e:
            print(f"Error extracting network data: {e}")

        return network_data

    def scrape_process_info(self) -> List[Dict]:
        """Scrape process tree items and their detailed panel content."""
        processes: List[Dict[str, Any]] = []

        try:
            process_elements = self.driver.find_elements(By.CSS_SELECTOR, ".process-tree-item")

            for index, elem in enumerate(process_elements, start=1):
                process: Dict[str, Any] = {"position": index}

                try:
                    content_elem = elem.find_element(By.CSS_SELECTOR, ".process-tree-item__content")
                except NoSuchElementException:
                    content_elem = None

                if content_elem:
                    try:
                        color_elem = content_elem.find_element(By.CSS_SELECTOR, ".process-tree-item__content-color")
                        color_class = color_elem.get_attribute("class") or ""
                        if "--danger" in color_class:
                            process["severity"] = "danger"
                        elif "--default" in color_class:
                            process["severity"] = "default"
                        elif "--" in color_class:
                            process["severity"] = color_class.split("--")[-1]
                        else:
                            process["severity"] = color_class or "unknown"
                    except NoSuchElementException:
                        pass

                try:
                    info_elem = elem.find_element(By.CSS_SELECTOR, ".process-tree-item-info")
                except NoSuchElementException:
                    info_elem = None

                if info_elem:
                    try:
                        name_elem = info_elem.find_element(
                            By.CSS_SELECTOR, ".process-tree-item-info__header-title-name"
                        )
                        name_value = name_elem.text.strip()
                        if name_value:
                            process["name"] = name_value
                    except NoSuchElementException:
                        pass

                    try:
                        pid_elem = info_elem.find_element(
                            By.CSS_SELECTOR, ".process-tree-item-info__header-pid"
                        )
                        pid_value = pid_elem.text.strip()
                        if pid_value:
                            process["pid"] = pid_value
                    except NoSuchElementException:
                        pass

                    indicator_details: List[Dict[str, str]] = []
                    indicator_elements = info_elem.find_elements(
                        By.CSS_SELECTOR, ".process-tree-item-info-indicators__list-item"
                    )
                    for indicator in indicator_elements:
                        detail: Dict[str, str] = {}
                        label_text = indicator.text.strip()
                        if label_text:
                            detail["label"] = label_text
                        tooltip_text = self._hover_and_get_tooltip(indicator)
                        if tooltip_text:
                            detail["tooltip"] = tooltip_text
                        if detail:
                            indicator_details.append(detail)
                    if indicator_details:
                        process["indicators"] = indicator_details

                clicked = False
                try:
                    elem.click()
                    clicked = True
                except Exception:
                    try:
                        self.driver.execute_script("arguments[0].click();", elem)
                        clicked = True
                    except Exception:
                        pass

                details: Dict[str, Any] = {}

                if clicked:
                    time.sleep(0.5)
                    try:
                        score_elem = WebDriverWait(self.driver, 4).until(
                            EC.presence_of_element_located((By.CSS_SELECTOR, ".details-block__chart-title"))
                        )
                        score_text = score_elem.text.strip()
                        if score_text:
                            details["score"] = score_text
                    except TimeoutException:
                        pass

                    try:
                        cmd_elem = self.driver.find_element(By.CSS_SELECTOR, ".process-cmd_content")
                        span_texts = [span.text.strip() for span in cmd_elem.find_elements(By.TAG_NAME, "span") if span.text.strip()]
                        if span_texts:
                            details["command"] = " ".join(span_texts)
                    except NoSuchElementException:
                        pass

                    try:
                        indicators_wrapper = self.driver.find_element(
                            By.CSS_SELECTOR, ".details-indicators__content-wrapper"
                        )
                        indicator_groups: List[Dict[str, Any]] = []
                        for section in indicators_wrapper.find_elements(
                            By.CSS_SELECTOR, ".details-indicators__indicator"
                        ):
                            section_class = section.get_attribute("class") or ""
                            if "warning" in section_class:
                                category = "warning"
                            elif "danger" in section_class:
                                category = "danger"
                            elif "other" in section_class:
                                category = "other"
                            else:
                                category = section_class.strip()

                            entries: List[Dict[str, Any]] = []
                            for wrapper in section.find_elements(
                                By.CSS_SELECTOR, ".details-indicators__item-wrapper"
                            ):
                                entry: Dict[str, Any] = {}
                                try:
                                    mitre_block = wrapper.find_element(
                                        By.CSS_SELECTOR, ".details-mitre-incidents"
                                    )
                                    mitre_entry: Dict[str, Any] = {}
                                    try:
                                        technique_btn = mitre_block.find_element(
                                            By.CSS_SELECTOR, ".mitre-info__technique"
                                        )
                                        technique_id = technique_btn.text.strip()
                                        if technique_id:
                                            mitre_entry["technique_id"] = technique_id
                                    except NoSuchElementException:
                                        pass
                                    try:
                                        technique_name_elem = mitre_block.find_element(
                                            By.CSS_SELECTOR, ".mitre-info__name"
                                        )
                                        technique_name = technique_name_elem.text.strip()
                                        if technique_name:
                                            mitre_entry["technique_name"] = technique_name
                                    except NoSuchElementException:
                                        pass
                                    incident_texts = [
                                        btn.text.strip()
                                        for btn in mitre_block.find_elements(
                                            By.CSS_SELECTOR,
                                            ".details-mitre-incidents__item .details-incident",
                                        )
                                        if btn.text.strip()
                                    ]
                                    if incident_texts:
                                        mitre_entry["incidents"] = incident_texts
                                    if mitre_entry:
                                        entry["mitre"] = mitre_entry
                                except NoSuchElementException:
                                    pass

                                text_content = wrapper.text.strip()
                                if text_content and "mitre" not in entry:
                                    entry["text"] = text_content

                                if entry:
                                    entries.append(entry)

                            if entries:
                                indicator_groups.append({"category": category, "entries": entries})

                        if indicator_groups:
                            details["indicator_groups"] = indicator_groups
                    except NoSuchElementException:
                        pass

                if details:
                    process["details"] = details

                if process.get("name") or process.get("pid"):
                    processes.append(process)

        except Exception as e:
            print(f"Error extracting process info: {e}")

        return processes

    def scrape_deep_analysis(self) -> Dict[str, Any]:
        """Scrape Deep Analysis sections (HTTP, Connections, DNS, Threats)."""
        data: Dict[str, Any] = {
            "http_requests": [],
            "connections": [],
            "dns_requests": [],
            "threats": [],
            "files": [],
        }

        try:
            navigation_items = self.driver.find_elements(
                By.CSS_SELECTOR, "li.deep-analysis-navigation-item"
            )
            if not navigation_items:
                return data

            sections_order = [
                "http_requests",
                "connections",
                "dns_requests",
                "threats",
                "files",
            ]

            for index, nav_item in enumerate(navigation_items):
                if index >= len(sections_order):
                    break

                section_key = sections_order[index]

                try:
                    self.driver.execute_script(
                        "arguments[0].scrollIntoView({block: 'center'});",
                        nav_item,
                    )
                except Exception:
                    pass

                try:
                    nav_item.click()
                except Exception:
                    try:
                        self.driver.execute_script("arguments[0].click();", nav_item)
                    except Exception:
                        continue

                time.sleep(0.3)
                self._wait_for_deep_analysis_section(section_key, timeout=8.0)

                if section_key == "http_requests":
                    data[section_key] = self._scrape_http_requests_section()
                elif section_key == "connections":
                    data[section_key] = self._scrape_connections_section()
                elif section_key == "dns_requests":
                    data[section_key] = self._scrape_dns_requests_section()
                elif section_key == "threats":
                    data[section_key] = self._scrape_threats_section()
                elif section_key == "files":
                    data[section_key] = self._scrape_files_section()
                else:
                    data[section_key] = []

        except Exception as exc:
            print(f"Error extracting deep analysis data: {exc}")

        return data

    def _wait_for_deep_analysis_section(self, section_key: str, timeout: float = 6.0) -> bool:
        """Wait for a Deep Analysis section to finish loading after tab change."""
        section_map = {
            "http_requests": {
                "container": "#deep-analysis-reqs-table",
                "row": ".reqs-table-item",
                "empty": ".no-data",
                "loading": ".loading, .ar-preloader",
            },
            "connections": {
                "container": "#deep-analysis-conns-table",
                "row": ".conns-table-item",
                "empty": ".no-data",
                "loading": ".loading, .ar-preloader",
            },
            "dns_requests": {
                "container": "#deep-analysis-dns-table",
                "row": ".dns-table-item",
                "empty": ".no-data",
                "loading": ".loading, .ar-preloader",
            },
            "threats": {
                "container": "#deep-analysis-threat-table",
                "row": ".threat-table-item",
                "empty": ".no-data",
                "loading": ".loading, .ar-preloader",
            },
            "files": {
                "container": "#deep-analysis-files-table",
                "row": ".deep-analysis-files-table-item, .files-table-item",
                "empty": ".no-data",
                "loading": ".loading, .ar-preloader",
            },
        }

        config = section_map.get(section_key)
        if not config:
            time.sleep(0.3)
            return False

        container_selector = config["container"]
        row_selector = config.get("row")
        empty_selector = config.get("empty")
        loading_selector = config.get("loading")

        end_time = time.time() + timeout

        while time.time() < end_time:
            self._check_for_bot_challenge()
            try:
                container = self.driver.find_element(By.CSS_SELECTOR, container_selector)
                if not container.is_displayed():
                    time.sleep(0.25)
                    continue

                if loading_selector and container.find_elements(By.CSS_SELECTOR, loading_selector):
                    time.sleep(0.25)
                    continue

                if row_selector:
                    rows = container.find_elements(By.CSS_SELECTOR, row_selector)
                    if rows:
                        return True

                if empty_selector and container.find_elements(By.CSS_SELECTOR, empty_selector):
                    return True

            except (NoSuchElementException, StaleElementReferenceException):
                pass
            except Exception:
                break

            time.sleep(0.25)

        return False

    def _scrape_http_requests_section(self) -> List[Dict[str, Any]]:
        """Scrape HTTP requests table from Deep Analysis section."""
        results: List[Dict[str, Any]] = []

        try:
            container = self.driver.find_element(
                By.CSS_SELECTOR,
                "#deep-analysis-reqs-table",
            )
        except NoSuchElementException:
            return results

        try:
            rows = container.find_elements(
                By.CSS_SELECTOR,
                ".reqs-table-wrapper__table > li.reqs-table-item",
            )
        except Exception:
            rows = []

        for row in rows:
            entry: Dict[str, Any] = {}

            def extract_text(selector: str) -> str:
                try:
                    element = row.find_element(By.CSS_SELECTOR, selector)
                    text = element.text.strip()
                    if not text and element.get_attribute("data-original-title"):
                        return element.get_attribute("data-original-title").strip()
                    return text
                except NoSuchElementException:
                    return ""

            entry["timeshift"] = extract_text(
                ".reqs-table-item__content-timeshift"
            )

            headers_content = ""
            try:
                headers_elem = row.find_element(
                    By.CSS_SELECTOR,
                    ".reqs-table-item__content-headers",
                )
                headers_content = headers_elem.text.strip()
            except NoSuchElementException:
                headers_content = ""
            if headers_content:
                entry["headers"] = headers_content

            reputation_text = ""
            try:
                rep_elem = row.find_element(
                    By.CSS_SELECTOR,
                    ".reqs-table-item__content-rep .col-rep",
                )
                reputation_text = rep_elem.get_attribute("data-original-title") or rep_elem.text
                reputation_text = (reputation_text or "").strip()
            except NoSuchElementException:
                reputation_text = ""
            if reputation_text:
                entry["reputation"] = reputation_text

            entry["pid"] = extract_text(
                ".reqs-table-item__content-pid"
            )

            entry["process_name"] = extract_text(
                ".reqs-table-item__content-processName"
            )

            try:
                flag_elem = row.find_element(
                    By.CSS_SELECTOR,
                    ".reqs-table-item__content-flag .flag-icon",
                )
                flag_classes = flag_elem.get_attribute("class") or ""
                entry["country_code"] = next(
                    (cls.replace("flag-icon-", "") for cls in flag_classes.split() if cls.startswith("flag-icon-")),
                    "",
                )
            except NoSuchElementException:
                pass

            entry["url"] = extract_text(
                ".reqs-table-item__content-url-text"
            )

            try:
                size_elem = row.find_element(
                    By.CSS_SELECTOR,
                    ".reqs-table-item__content-traffic .content-traffic__size-block",
                )
                size_text = size_elem.text.strip()
                if size_text:
                    entry["content_size"] = size_text
                content_type = ""
                try:
                    type_elem = size_elem.find_element(By.CSS_SELECTOR, ".size-block__content-type")
                    content_type = type_elem.text.strip()
                except NoSuchElementException:
                    content_type = ""
                if content_type:
                    entry["content_type"] = content_type
            except NoSuchElementException:
                pass

            results.append(entry)

        return results

    def _scrape_connections_section(self) -> List[Dict[str, Any]]:
        """Scrape Connections table from Deep Analysis section."""
        results: List[Dict[str, Any]] = []

        try:
            container = self.driver.find_element(
                By.CSS_SELECTOR,
                "#deep-analysis-conns-table",
            )
        except NoSuchElementException:
            return results

        try:
            rows = container.find_elements(
                By.CSS_SELECTOR,
                ".conns-table-wrapper__table > li.conns-table-item",
            )
        except Exception:
            rows = []

        for row in rows:
            entry: Dict[str, Any] = {}

            def safe_text(selector: str) -> str:
                try:
                    element = row.find_element(By.CSS_SELECTOR, selector)
                    text = element.text.strip()
                    if not text:
                        text = (element.get_attribute("data-original-title") or "").strip()
                    return text
                except NoSuchElementException:
                    return ""

            entry["timeshift"] = safe_text(
                ".conns-table-item__content-timeshift"
            )

            entry["protocol"] = safe_text(
                ".conns-table-item__content-proto"
            )

            try:
                rep_elem = row.find_element(
                    By.CSS_SELECTOR,
                    ".conns-table-item__content-rep .col-rep",
                )
                reputation = rep_elem.get_attribute("data-original-title") or rep_elem.text
                entry["reputation"] = reputation.strip()
            except NoSuchElementException:
                pass

            entry["pid"] = safe_text(
                ".conns-table-item__content-pid"
            )

            entry["process_name"] = safe_text(
                ".conns-table-item__content-processName"
            )

            try:
                flag_elem = row.find_element(
                    By.CSS_SELECTOR,
                    ".conns-table-item__content-flag .flag-icon",
                )
                flag_classes = flag_elem.get_attribute("class") or ""
                entry["country_code"] = next(
                    (cls.replace("flag-icon-", "") for cls in flag_classes.split() if cls.startswith("flag-icon-")),
                    "",
                )
            except NoSuchElementException:
                try:
                    if row.find_element(By.CSS_SELECTOR, ".conns-table-item__content-flag .fa-question"):
                        entry["country_code"] = "unknown"
                except NoSuchElementException:
                    pass

            entry["ip"] = safe_text(
                ".conns-table-item__content-ip-text"
            )

            entry["port"] = safe_text(
                ".conns-table-item__content-port"
            )

            domain_text = safe_text(
                ".conns-table-item__content-domain .conns-table-item__content-ip-text"
            )
            if not domain_text:
                domain_text = safe_text(
                    ".conns-table-item__content-domain"
                )
            if domain_text:
                entry["domain"] = domain_text

            asn_text = safe_text(
                ".conns-table-item__content-asn .conns-table-item__content-ip-text"
            )
            if not asn_text:
                asn_text = safe_text(
                    ".conns-table-item__content-asn"
                )
            if asn_text:
                entry["asn"] = asn_text

            try:
                traffic_elem = row.find_element(
                    By.CSS_SELECTOR,
                    ".conns-table-item__content-traffic",
                )
                upload_text = safe_text(
                    ".content-traffic__left-upload span"
                )
                download_text = safe_text(
                    ".content-traffic__right span:not(.no-data)"
                )
                message_text = safe_text(
                    ".conns-table-item__content-traffic-message"
                )
                traffic: Dict[str, Any] = {}
                if upload_text:
                    traffic["upload"] = upload_text
                if download_text:
                    traffic["download"] = download_text
                if message_text and message_text.lower() != "no data":
                    traffic["message"] = message_text
                if traffic:
                    entry["traffic"] = traffic
            except NoSuchElementException:
                pass

            results.append(entry)

        return results

    def _scrape_dns_requests_section(self) -> List[Dict[str, Any]]:
        """Scrape DNS requests table from Deep Analysis section."""
        results: List[Dict[str, Any]] = []

        try:
            container = self.driver.find_element(
                By.CSS_SELECTOR,
                "#deep-analysis-dns-table",
            )
        except NoSuchElementException:
            return results

        try:
            rows = container.find_elements(
                By.CSS_SELECTOR,
                ".dns-table-wrapper__table > li.dns-table-item",
            )
        except Exception:
            rows = []

        for row in rows:
            entry: Dict[str, Any] = {}

            def safe_text(selector: str, attr: Optional[str] = "data-original-title") -> str:
                try:
                    element = row.find_element(By.CSS_SELECTOR, selector)
                    text = element.text.strip()
                    if text:
                        return text
                    if attr:
                        attr_value = element.get_attribute(attr) or ""
                        attr_value = attr_value.strip()
                        if attr_value and attr_value.lower() != "null":
                            return attr_value
                    return ""
                except NoSuchElementException:
                    return ""

            entry["timeshift"] = safe_text(
                ".dns-table-item__content-timeshift",
            )

            status_text = safe_text(
                ".dns-table-item__content-status .network-item__status",
                attr=None,
            )
            if status_text:
                entry["status"] = status_text

            try:
                status_wrapper = row.find_element(
                    By.CSS_SELECTOR,
                    ".dns-table-item__content-status .dns-status-wrapper",
                )
                status_classes = status_wrapper.get_attribute("class") or ""
                status_tokens = status_classes.split()
                for token in status_tokens:
                    if token in {"success", "warning", "danger", "error", "blocked"}:
                        entry["status_class"] = token
                        break
                if "status_class" not in entry and status_classes.strip():
                    entry["status_class"] = status_classes.strip()
            except NoSuchElementException:
                pass

            try:
                rep_elem = row.find_element(
                    By.CSS_SELECTOR,
                    ".dns-table-item__content-rep .col-rep",
                )
                rep_text = (rep_elem.get_attribute("data-original-title") or "").strip()
                if rep_text and rep_text.lower() != "null":
                    entry["reputation"] = rep_text
                else:
                    try:
                        use_elem = rep_elem.find_element(By.TAG_NAME, "use")
                        href_value = (
                            use_elem.get_attribute("xlink:href")
                            or use_elem.get_attribute("href")
                            or ""
                        ).strip()
                        if href_value:
                            entry["reputation_icon"] = href_value.lstrip("#")
                    except NoSuchElementException:
                        pass
            except NoSuchElementException:
                pass

            domain_text = safe_text(
                ".dns-table-item__content-dns .dns-table-item__content-domain-text span",
            )
            if not domain_text:
                domain_text = safe_text(
                    ".dns-table-item__content-dns",
                )
            if domain_text:
                entry["domain"] = domain_text

            ip_fields = row.find_elements(
                By.CSS_SELECTOR,
                ".dns-table-item__content-ip .network-copy-field",
            )
            ips: List[str] = []
            for field in ip_fields:
                ip_text = field.text.strip()
                if not ip_text:
                    ip_text = (field.get_attribute("data-original-title") or "").strip()
                ip_text = ip_text.replace("\n", " ").strip()
                if ip_text and ip_text.lower() != "copy":
                    normalized = " ".join(ip_text.split())
                    if normalized not in ips:
                        ips.append(normalized)
            if ips:
                entry["ips"] = ips
                if len(ips) == 1:
                    entry["ip"] = ips[0]

            if entry:
                results.append(entry)

        return results

    def _scrape_files_section(self) -> List[Dict[str, Any]]:
        """Scrape Files table from Deep Analysis section."""
        results: List[Dict[str, Any]] = []

        try:
            container = self.driver.find_element(
                By.CSS_SELECTOR,
                "#deep-analysis-files-table",
            )
        except NoSuchElementException:
            return results

        try:
            rows = container.find_elements(
                By.CSS_SELECTOR,
                ".files-table-wrapper__table > li",
            )
        except Exception:
            rows = []

        def normalize(value: str) -> str:
            return " ".join(value.split()) if value else ""

        for row in rows:
            entry: Dict[str, Any] = {}

            def safe_text(selector: str, attr: Optional[str] = "data-original-title") -> str:
                try:
                    element = row.find_element(By.CSS_SELECTOR, selector)
                    text_content = normalize(element.text.strip())
                    if text_content:
                        return text_content
                    if attr:
                        attr_value = (element.get_attribute(attr) or "").strip()
                        attr_value = normalize(attr_value)
                        if attr_value and attr_value.lower() != "null":
                            return attr_value
                    return ""
                except NoSuchElementException:
                    return ""

            timeshift = safe_text(".files-table-item__content-timeshift")
            if timeshift:
                entry["timeshift"] = timeshift

            pid_text = safe_text(
                ".files-table-item__content-pid .col-pid-text",
                attr=None,
            )
            if pid_text:
                entry["pid"] = pid_text

            process_text = safe_text(
                ".files-table-item__content-processName .col-processName-text",
                attr=None,
            )
            if process_text:
                entry["process_name"] = process_text

            path_text = safe_text(
                ".files-table-item__content-url-text",
                attr=None,
            )
            if path_text:
                entry["path"] = path_text

            try:
                size_block = row.find_element(
                    By.CSS_SELECTOR,
                    ".files-table-item__size-content",
                )
            except NoSuchElementException:
                size_block = None

            if size_block is not None:
                size_info: Dict[str, Any] = {}
                block_class = size_block.get_attribute("class") or ""
                for severity in ("danger", "warning", "success"):
                    if f"--{severity}" in block_class:
                        size_info["severity"] = severity
                        break

                def size_text(selector: str) -> str:
                    try:
                        element = size_block.find_element(By.CSS_SELECTOR, selector)
                        text_content = normalize(element.text.strip())
                        if text_content:
                            return text_content
                        attr_value = (element.get_attribute("data-original-title") or "").strip()
                        attr_value = normalize(attr_value)
                        if attr_value and attr_value.lower() != "null":
                            return attr_value
                        return ""
                    except NoSuchElementException:
                        return ""

                converted_text = size_text(".files-table-item__size-converted")
                if converted_text:
                    size_info["size"] = converted_text

                content_type = size_text(".files-table-item__size-type")
                if not content_type and size_block.find_elements(By.CSS_SELECTOR, ".no-data"):
                    content_type = "no data"
                if content_type:
                    size_info["content_type"] = content_type

                if not size_info:
                    raw_size = normalize(size_block.text.strip())
                    if raw_size:
                        size_info["raw"] = raw_size

                if size_info:
                    entry["size"] = size_info

            try:
                mistral_button = row.find_element(
                    By.CSS_SELECTOR,
                    "button[data-sm-id='deep-analysis-network-files-mistral']",
                )
                if mistral_button.is_displayed():
                    entry["has_mistral_button"] = True
            except NoSuchElementException:
                pass

            if entry:
                results.append(entry)

        return results

    def _scrape_threats_section(self) -> List[Dict[str, Any]]:
        """Scrape Threats table from Deep Analysis section."""
        results: List[Dict[str, Any]] = []

        try:
            container = self.driver.find_element(
                By.CSS_SELECTOR,
                "#deep-analysis-threat-table",
            )
        except NoSuchElementException:
            return results

        try:
            rows = container.find_elements(
                By.CSS_SELECTOR,
                ".threat-table-wrapper__table > li.threat-table-item",
            )
        except Exception:
            rows = []

        for row in rows:
            entry: Dict[str, Any] = {}

            def safe_text(selector: str) -> str:
                try:
                    element = row.find_element(By.CSS_SELECTOR, selector)
                    text = element.text.strip()
                    if text:
                        return text
                    return ""
                except NoSuchElementException:
                    return ""

            entry["timeshift"] = safe_text(
                ".threats-table-item__content-timeshift",
            )

            try:
                class_wrapper = row.find_element(
                    By.CSS_SELECTOR,
                    ".threats-table-item__content-class .threat-class-wrapper",
                )
                threat_class_text = class_wrapper.text.strip()
                if threat_class_text:
                    entry["class"] = threat_class_text
                wrapper_classes = class_wrapper.get_attribute("class") or ""
                for token in wrapper_classes.split():
                    if token.startswith("threat-class-wrapper--"):
                        entry["class_level"] = token.replace("threat-class-wrapper--", "")
                        break
                if "class_level" not in entry and wrapper_classes.strip():
                    entry["class_level"] = wrapper_classes.strip()
            except NoSuchElementException:
                pass

            pid_text = safe_text(
                ".threats-table-item__content-pid",
            )
            if pid_text and pid_text.lower() != "no data":
                entry["pid"] = pid_text

            process_text = safe_text(
                ".threats-table-item__content-processName",
            )
            if process_text and process_text.lower() != "no data":
                entry["process_name"] = process_text

            message_text = safe_text(
                ".threats-table-item__content-message .suricata-message",
            )
            if message_text:
                entry["message"] = message_text

            try:
                row.find_element(
                    By.CSS_SELECTOR,
                    ".threats-table-item__content-message .mistralAi-button",
                )
                entry["has_mistral_button"] = True
            except NoSuchElementException:
                pass

            if entry:
                results.append(entry)

        return results

    def scrape_static_info(self) -> Dict:
        """Scrape static analysis information."""
        static_info = {}
        
        try:
            try:
                trid_elem = self.driver.find_element(
                    By.XPATH, "//div[contains(text(), 'TRiD')]"
                )
                static_info["trid"] = trid_elem.text.strip()
            except NoSuchElementException:
                static_info["trid"] = ""
            
            try:
                exif_elements = self.driver.find_elements(
                    By.XPATH, "//div[contains(text(), 'EXIF') or contains(@class, 'exif')]"
                )
                exif_data = []
                for elem in exif_elements:
                    exif_data.append(elem.text.strip())
                static_info["exif"] = exif_data
            except Exception:
                static_info["exif"] = []
                
        except Exception as e:
            print(f"Error extracting static info: {e}")

        return static_info

    def find_and_click_pcap_download(self) -> bool:
        """Find and click PCAP download button."""
        try:
            # Step 1: Click the network/pcap tab button
            print("    Looking for network PCAP tab...")
            try:
                pcap_tab = self.driver.find_element(
                    By.XPATH,
                    "//button[@data-sm-id='deep-analysis-network-pcap' and contains(normalize-space(.), 'PCAP')]"
                )
                pcap_tab.click()
                print("    ✓ Clicked network PCAP tab")
                time.sleep(2)
                self._check_for_bot_challenge()
            except NoSuchElementException:
                print("    ✗ PCAP tab not found")
                return False
            
            # Step 2: Find and click the dropdown item with "PCAP" text
            print("    Looking for PCAP download button...")
            self._check_for_bot_challenge()
            try:
                # Find button with class dropdown-item that contains span with text "PCAP"
                pcap_button = self.driver.find_element(
                    By.XPATH, 
                    "//button[contains(@class, 'dropdown-item')]//span[contains(text(), 'PCAP')]/.."
                )
                self._check_for_bot_challenge()
                pcap_button.click()
                print("    ✓ Clicked PCAP download button")
                time.sleep(3)
                self._check_for_bot_challenge()
                return True
            except NoSuchElementException:
                print("    ✗ PCAP download button not found")
                return False
                    
        except Exception as e:
            print(f"    ✗ Error clicking PCAP download: {e}")
            return False

    def download_pcap(self, url: str, task_id: str, report_data: Dict) -> Optional[str]:
        """Download PCAP file and label it appropriately."""
        try:
            print(f"  Attempting to download PCAP...")
            
            # Click the PCAP download buttons
            if not self.find_and_click_pcap_download():
                print(f"  ✗ Could not download PCAP for task {task_id}")
                return None
            
            # Prepare the expected filename
            verdict = report_data.get("general_info", {}).get("verdict", "unknown")
            file_name = report_data.get("general_info", {}).get("file_name", "unknown")
            md5 = report_data.get("general_info", {}).get("md5", "")[:8]
            
            safe_file_name = re.sub(r'[<>:"/\\|?*]', '_', file_name)[:50]
            pcap_filename = f"{task_id}_{verdict}_{safe_file_name}_{md5}.pcap"
            pcap_path = self.pcap_dir / pcap_filename
            
            print(f"  ✓ PCAP download initiated for task {task_id}")
            time.sleep(5)  # Wait for download to complete
            self._check_for_bot_challenge()
            
            return str(pcap_path)
                
        except Exception as e:
            print(f"  ✗ Error downloading PCAP for task {task_id}: {e}")
            return None

    def scrape_report(self, url: str) -> Optional[Dict]:
        """Scrape a single report page."""
        task_id = self._extract_task_id(url)
        if not task_id:
            print(f"Could not extract task ID from URL: {url}")
            return None

        print(f"\nScraping task {task_id}...")
        print(f"  URL: {url}")
        
        try:
            print(f"  Loading page...")
            self.driver.get(url)
            self._handle_login_if_needed(url)
            self._check_for_bot_challenge()
            
            if not self._wait_for_page_load(initial_wait=5):
                print(f"  ✗ Failed to load page after waiting: {url}")
                print(f"  Retrying with longer wait...")
                time.sleep(10)
                
                if not self._wait_for_page_load(initial_wait=10):
                    print(f"  ✗ Page still not loaded, skipping: {url}")
                    return None
            
            print(f"  ✓ Page loaded successfully")
            print(f"  Extracting data...")
            report_data = {}
            report_data = {
                "task_id": task_id,
                "url": url,
                "general_info": self.scrape_general_info(),
                "process_info": self.scrape_process_info(),
                "ioc_details": self.scrape_ioc_details(),
                "mitre_attack": self.scrape_mitre_attack(),
                "deep_analysis": self.scrape_deep_analysis(),
            }
            
            pcap_path = self.download_pcap(url, task_id, report_data)
            if pcap_path:
                report_data["pcap_file"] = pcap_path
            
            report_file = self.output_dir / f"{task_id}_report.json"
            with open(report_file, "w", encoding="utf-8") as f:
                json.dump(report_data, f, indent=2, ensure_ascii=False)
            
            print(f"  ✓ Scraped task {task_id}")
            return report_data
            
        except TimeoutException as e:
            print(f"  ✗ Timeout error for task {task_id}: {e}")
            print(f"     This usually means slow connection. Try increasing --timeout value.")
            return None
        except Exception as e:
            print(f"  ✗ Error scraping task {task_id}: {e}")
            return None

    def run(self):
        """Main execution loop."""
        print("=" * 60)
        print("ANY.RUN Report Scraper")
        print("=" * 60)
        
        try:
            df = pd.read_excel(self.input_excel)
            urls = df["report_url"].tolist()
            print(f"\nLoaded {len(urls)} URLs from {self.input_excel}")
        except Exception as e:
            print(f"Error loading Excel file: {e}")
            return
        
        urls_to_process = [url for url in urls if url not in self.processed_urls]
        print(f"Already processed: {len(self.processed_urls)}")
        print(f"Remaining to process: {len(urls_to_process)}")
        
        if not urls_to_process:
            print("\nAll URLs have been processed!")
            return
        
        print("\nInitializing browser...")
        self._init_driver()
        self._initial_login()
        
        try:
            for i, url in enumerate(urls_to_process, 1):
                print(f"\n[{i}/{len(urls_to_process)}] Processing: {url}")
                
                result = self.scrape_report(url)
                
                if result:
                    self.processed_urls.add(url)
                    self._save_checkpoint()
                
                if i < len(urls_to_process):
                    print(f"  Waiting {self.page_delay} seconds...")
                    time.sleep(self.page_delay)
            
            print("\n" + "=" * 60)
            print("Scraping completed!")
            print(f"Total processed: {len(self.processed_urls)}")
            print(f"Data saved to: {self.output_dir}")
            print(f"PCAP files saved to: {self.pcap_dir}")
            print("=" * 60)
            
        except KeyboardInterrupt:
            print("\n\nScraping interrupted by user.")
            print(f"Progress saved. Processed {len(self.processed_urls)} URLs so far.")
        finally:
            self._close_driver()

    def create_summary_dataset(self):
        """Create a summary dataset from all scraped reports."""
        print("\nCreating summary dataset...")
        
        report_files = list(self.output_dir.glob("*_report.json"))
        
        if not report_files:
            print("No report files found!")
            return
        
        dataset = []
        
        for report_file in report_files:
            try:
                with open(report_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                
                row = {
                    "task_id": data.get("task_id", ""),
                    "url": data.get("url", ""),
                    "file_name": data.get("general_info", {}).get("file_name", ""),
                    "verdict": data.get("general_info", {}).get("verdict", ""),
                    "os": data.get("general_info", {}).get("os", ""),
                    "md5": data.get("general_info", {}).get("md5", ""),
                    "sha1": data.get("general_info", {}).get("sha1", ""),
                    "sha256": data.get("general_info", {}).get("sha256", ""),
                    "mime_type": data.get("general_info", {}).get("mime_type", ""),
                    "tags": ", ".join(data.get("general_info", {}).get("tags", [])),
                    "num_behaviors": len(data.get("behavior_activities", [])),
                    "num_mitre_techniques": len(data.get("mitre_attack", {}).get("techniques", [])),
                    "mitre_techniques": ", ".join([
                        m.get("technique_id", "")
                        for m in data.get("mitre_attack", {}).get("techniques", [])
                    ]),
                    "num_network_connections": len(data.get("network_data", [])),
                    "num_processes": len(data.get("process_info", [])),
                    "pcap_file": data.get("pcap_file", ""),
                }
                
                dataset.append(row)
                
            except Exception as e:
                print(f"Error processing {report_file}: {e}")
                continue
        
        if dataset:
            df = pd.DataFrame(dataset)
            csv_path = self.output_dir / "dataset_summary.csv"
            df.to_csv(csv_path, index=False)
            print(f"Summary dataset saved to: {csv_path}")
            print(f"Total records: {len(dataset)}")
        else:
            print("No data to save!")


# ============================================================================
# DATASET ANALYZER CLASS
# ============================================================================

class DatasetAnalyzer:
    """Analyze scraped ANY.RUN dataset."""
    
    def __init__(self, scraped_dir="scraped_data", pcap_dir="pcap_files"):
        self.scraped_dir = Path(scraped_dir)
        self.pcap_dir = Path(pcap_dir)
        self.summary_df = None
        
    def load_summary(self):
        """Load the summary CSV."""
        summary_path = self.scraped_dir / "dataset_summary.csv"
        if summary_path.exists():
            self.summary_df = pd.read_csv(summary_path)
            return True
        return False
    
    def print_statistics(self):
        """Print overall dataset statistics."""
        if self.summary_df is None:
            if not self.load_summary():
                print("Summary CSV not found. Run scraper first.")
                return
        
        df = self.summary_df
        
        print("=" * 60)
        print("DATASET STATISTICS")
        print("=" * 60)
        
        print(f"\n📊 Total Reports: {len(df)}")
        
        print("\n🎯 Verdicts:")
        verdict_counts = df['verdict'].value_counts()
        for verdict, count in verdict_counts.items():
            percentage = (count / len(df)) * 100
            print(f"   {verdict}: {count} ({percentage:.1f}%)")
        
        print("\n💻 Operating Systems:")
        os_counts = df['os'].value_counts().head(5)
        for os, count in os_counts.items():
            print(f"   {os}: {count}")
        
        print("\n🏷️  MIME Types:")
        mime_counts = df['mime_type'].value_counts().head(5)
        for mime, count in mime_counts.items():
            print(f"   {mime}: {count}")
        
        print("\n⚠️  Behavior Activities:")
        total_behaviors = df['num_behaviors'].sum()
        avg_behaviors = df['num_behaviors'].mean()
        print(f"   Total: {total_behaviors}")
        print(f"   Average per report: {avg_behaviors:.1f}")
        print(f"   Max: {df['num_behaviors'].max()}")
        
        print("\n🎯 MITRE ATT&CK Coverage:")
        total_techniques = df['num_mitre_techniques'].sum()
        avg_techniques = df['num_mitre_techniques'].mean()
        print(f"   Total technique occurrences: {total_techniques}")
        print(f"   Average per report: {avg_techniques:.1f}")
        print(f"   Reports with techniques: {len(df[df['num_mitre_techniques'] > 0])}")
        
        print("\n🌐 Network Activity:")
        total_connections = df['num_network_connections'].sum()
        avg_connections = df['num_network_connections'].mean()
        print(f"   Total connections: {total_connections}")
        print(f"   Average per report: {avg_connections:.1f}")
        
        print("\n⚙️  Process Activity:")
        total_processes = df['num_processes'].sum()
        avg_processes = df['num_processes'].mean()
        print(f"   Total processes: {total_processes}")
        print(f"   Average per report: {avg_processes:.1f}")
        
        print("\n📦 PCAP Files:")
        pcap_count = len(df[df['pcap_file'].notna() & (df['pcap_file'] != '')])
        print(f"   Downloaded: {pcap_count}")
        print(f"   Missing: {len(df) - pcap_count}")
        
        print("\n" + "=" * 60)
    
    def analyze_mitre_techniques(self, top_n=20):
        """Analyze MITRE ATT&CK technique distribution."""
        if self.summary_df is None:
            if not self.load_summary():
                return
        
        print("\n" + "=" * 60)
        print(f"TOP {top_n} MITRE ATT&CK TECHNIQUES")
        print("=" * 60)
        
        all_techniques = []
        for techniques_str in self.summary_df['mitre_techniques'].dropna():
            if techniques_str and techniques_str.strip():
                techniques = [t.strip() for t in str(techniques_str).split(',')]
                all_techniques.extend(techniques)
        
        if not all_techniques:
            print("No MITRE techniques found in dataset.")
            return
        
        technique_counts = Counter(all_techniques)
        
        print(f"\nTotal unique techniques: {len(technique_counts)}")
        print(f"Total technique occurrences: {len(all_techniques)}")
        print(f"\nTop {top_n} most common techniques:\n")
        
        for i, (technique, count) in enumerate(technique_counts.most_common(top_n), 1):
            percentage = (count / len(self.summary_df)) * 100
            print(f"{i:2d}. {technique:10s} - {count:4d} occurrences ({percentage:.1f}% of reports)")


# ============================================================================
# SUBSET CREATOR UTILITIES
# ============================================================================

def create_subset(input_file="reports.xlsx", num_urls=100, output_file=None):
    """Create a subset Excel file with specified number of URLs."""
    if output_file is None:
        output_file = f"reports_{num_urls}.xlsx"
    
    print(f"Creating subset: {num_urls} URLs from {input_file}")
    
    try:
        df = pd.read_excel(input_file)
        print(f"  Total URLs available: {len(df)}")
        
        if num_urls > len(df):
            print(f"  Warning: Requested {num_urls} but only {len(df)} available")
            num_urls = len(df)
        
        subset_df = df.head(num_urls)
        subset_df.to_excel(output_file, index=False)
        
        print(f"  ✓ Created {output_file} with {len(subset_df)} URLs")
        return output_file
        
    except Exception as e:
        print(f"  Error: {e}")
        return None


def create_batches(input_file="reports.xlsx", batch_size=1000, output_dir="batches"):
    """Create multiple batch files for processing."""
    output_path = Path(output_dir)
    output_path.mkdir(exist_ok=True)
    
    print(f"Creating batches: {batch_size} URLs per batch")
    
    try:
        df = pd.read_excel(input_file)
        total = len(df)
        num_batches = (total + batch_size - 1) // batch_size
        
        print(f"  Total URLs: {total}")
        print(f"  Batch size: {batch_size}")
        print(f"  Number of batches: {num_batches}")
        print()
        
        batch_files = []
        
        for i in range(num_batches):
            start_idx = i * batch_size
            end_idx = min(start_idx + batch_size, total)
            
            batch_df = df.iloc[start_idx:end_idx]
            batch_file = output_path / f"batch_{i+1:03d}.xlsx"
            
            batch_df.to_excel(batch_file, index=False)
            batch_files.append(str(batch_file))
            
            print(f"  ✓ Batch {i+1:3d}: {batch_file} ({len(batch_df)} URLs)")
        
        print(f"\n✓ Created {len(batch_files)} batch files in {output_dir}/")
        return batch_files
        
    except Exception as e:
        print(f"  Error: {e}")
        return []


# ============================================================================
# MAIN CLI
# ============================================================================

def main():
    """Main entry point with subcommands."""
    parser = argparse.ArgumentParser(
        description="Unified ANY.RUN Report Scraper - Scrape, analyze, and manage datasets"
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Command to run')
    
    # Scrape command (default for debugging)
    scrape_parser = subparsers.add_parser('scrape', help='Scrape reports')
    scrape_parser.add_argument('--input', default='reports.xlsx', help='Input Excel file')
    scrape_parser.add_argument('--output-dir', default='scraped_data', help='Output directory')
    scrape_parser.add_argument('--pcap-dir', default='pcap_files', help='PCAP directory')
    scrape_parser.add_argument('--checkpoint', default='scraper_checkpoint.json', help='Checkpoint file')
    scrape_parser.add_argument('--headless', action='store_true', help='Run in headless mode')
    scrape_parser.add_argument('--timeout', type=int, default=60, help='Wait timeout (seconds)')
    scrape_parser.add_argument('--page-load-timeout', type=int, default=120, help='Page load timeout')
    scrape_parser.add_argument('--delay', type=float, default=2.0, help='Delay between requests')
    scrape_parser.add_argument('--email',type=str,default="i221570@nu.edu.pk", help='Login email for ANY.RUN')
    scrape_parser.add_argument('--password',type=str,default="Ameerhamza@4", help='Login password for ANY.RUN')
    scrape_parser.add_argument('--smtp-host', default='smtp.gmail.com', help='SMTP server hostname for notifications')
    scrape_parser.add_argument('--smtp-port', type=int, default=587, help='SMTP server port')
    scrape_parser.add_argument('--smtp-username', default='malikameerhamzaqtb@gmail.com', help='SMTP username for notifications')
    scrape_parser.add_argument('--smtp-password', default='', help='SMTP password or app password')
    scrape_parser.add_argument('--smtp-from', default='malikameerhamzaqtb@gmail.com', help='From address for notification emails')
    scrape_parser.add_argument('--smtp-to', default='i221570@nu.edu.pk', help='Comma-separated recipients for notifications')
    scrape_parser.add_argument('--smtp-no-tls', action='store_true', help='Disable STARTTLS when sending email notifications')
    
    # Analyze command
    analyze_parser = subparsers.add_parser('analyze', help='Analyze scraped data')
    analyze_parser.add_argument('--scraped-dir', default='scraped_data', help='Scraped data directory')
    analyze_parser.add_argument('--top-n', type=int, default=20, help='Top N items to show')
    
    # Subset command
    subset_parser = subparsers.add_parser('subset', help='Create URL subset')
    subset_parser.add_argument('--input', default='reports.xlsx', help='Input file')
    subset_parser.add_argument('--num', type=int, default=100, help='Number of URLs')
    subset_parser.add_argument('--output', help='Output file')
    
    # Batch command
    batch_parser = subparsers.add_parser('batch', help='Create batches')
    batch_parser.add_argument('--input', default='reports.xlsx', help='Input file')
    batch_parser.add_argument('--size', type=int, default=1000, help='Batch size')
    batch_parser.add_argument('--output-dir', default='batches', help='Output directory')
    
    args = parser.parse_args()
    
    # Default to 'scrape' command if none specified (for easier debugging)
    if args.command is None:
        args.command = 'scrape'
        args.input = 'reports.xlsx'
        args.output_dir = 'scraped_data'
        args.pcap_dir = 'pcap_files'
        args.checkpoint = 'scraper_checkpoint.json'
        args.headless = False
        args.timeout = 60
        args.page_load_timeout = 120
        args.delay = 2.0
        args.email = "i221570@nu.edu.pk"
        args.password = "Ameerhamza@4"
    args.smtp_host = 'smtp.gmail.com'
    args.smtp_port = 587
    args.smtp_username = 'malikameerhamzaqtb@gmail.com'
    args.smtp_password = 'ogzm qkvw ppma mzzy'
    args.smtp_from = 'malikameerhamzaqtb@gmail.com'
    args.smtp_to = 'i221570@nu.edu.pk'
    args.smtp_no_tls = False
    
    if args.command == 'scrape':
        scraper = ReportScraper(
            input_excel=args.input,
            output_dir=args.output_dir,
            pcap_dir=args.pcap_dir,
            checkpoint_file=args.checkpoint,
            headless=args.headless,
            wait_timeout=args.timeout,
            page_delay=args.delay,
            page_load_timeout=args.page_load_timeout,
            login_email=args.email,
            login_password=args.password,
            smtp_host=args.smtp_host,
            smtp_port=args.smtp_port,
            smtp_username=args.smtp_username,
            smtp_password=args.smtp_password,
            smtp_from=args.smtp_from,
            smtp_to=args.smtp_to,
            smtp_use_tls=not args.smtp_no_tls,
        )
        scraper.run()
        scraper.create_summary_dataset()
        
    elif args.command == 'analyze':
        analyzer = DatasetAnalyzer(scraped_dir=args.scraped_dir)
        analyzer.print_statistics()
        analyzer.analyze_mitre_techniques(top_n=args.top_n)
        
    elif args.command == 'subset':
        create_subset(input_file=args.input, num_urls=args.num, output_file=args.output)
        
    elif args.command == 'batch':
        create_batches(input_file=args.input, batch_size=args.size, output_dir=args.output_dir)
        
    else:
        parser.print_help()
        print("\nExamples:")
        print("  python scraper.py scrape --headless")
        print("  python scraper.py scrape --timeout 120 --headless")
        print("  python scraper.py analyze")
        print("  python scraper.py subset --num 100")
        print("  python scraper.py batch --size 500")


if __name__ == "__main__":
    main()
