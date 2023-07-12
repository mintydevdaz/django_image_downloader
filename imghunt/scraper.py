from io import BytesIO
from datetime import datetime
import os
import shutil
from typing import Type, Union

import httpx
import validators
from PIL import Image
from playwright.sync_api import sync_playwright
from selectolax.parser import HTMLParser

# Custom type hint
ParsedHTML = Type[HTMLParser]

# Global variables
MIN_LINKS = 5
TEMP_DL_FOLDER = "imghunt/temp_dl"
TAGS = ["src", "srcset", "data-src", "data-srcset", "data-fallback-src"]


def check_url(query: str) -> Union[list[str], str]:
    if not validators.url(query):
        return ["Invalid URL. Try again!"]


def get_request(query: str) -> Union[httpx.Response, list[str]]:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36"  # noqa
    }
    try:
        response = httpx.get(query, headers=headers, follow_redirects=True)
        response.raise_for_status()
        return response
    except (httpx.HTTPError, httpx.RequestError) as error:
        return [f"Error accessing URL: {error}"]


def parse_html(response: httpx.Response) -> ParsedHTML:
    return HTMLParser(response.text)


def get_canonical_url(tree: ParsedHTML) -> Union[str, None]:
    """
    Fetches the canonical URL from the DOM head. Returns None
    if no canonical URL is found.
    """
    return (
        nodes[0].attributes.get("href")
        if (nodes := tree.css('link[rel="canonical"]'))
        else None
    )


def get_raw_image_links(tree: ParsedHTML, attributes: list[str]) -> list[str]:
    """
    Fetches all <img> nodes from DOM then extracts link(s) inside each node.
    Next, checks if a comma is detected in string. This indicates that there
    may be multiple links within string, typical of different resolutions of an
    image the browser can present to the user depending on the size of the
    viewport.
    """
    links = image_nodes(tree, attributes)
    return check_nested_links(links)


# ! Inside 'get_raw_image_links'
def image_nodes(tree: ParsedHTML, attributes: list[str]) -> list[str]:
    """Fetches all <img> nodes from DOM then extracts link(s) inside each node."""
    result = []
    for node in tree.css("img"):
        for i in attributes:
            if src := node.attributes.get(i):
                result.append(src)
    return result


# ! Inside 'get_raw_image_links'
def check_nested_links(links: list[str]) -> list[str]:
    """
    Extracts links where strings have multiple URLs nested inside.
    Typical where an <img> node is directed to deliver different resolutions
    depending on the viewport. Only collects valid URLs where multiple links
    are detected (i.e. passed through a validator func).

    Args:
        links (list[str]): Raw URLs extracted from <img> src nodes in DOM.

    Returns:
        list[str]: Combined list of URLs if any found.
    """
    url_filter = []
    if any(" " in link for link in links):
        for idx, link in enumerate(links):
            if " " in link:
                link = links.pop(idx)
                items = link.replace(",", "").split(" ")
                url_filter.extend(item for item in items if valid_url(item))
        return links + url_filter
    return links


# ! Inside 'check_nested_links'
def valid_url(url: str):
    return bool(validators.url(url))


def run_playwright(url: str, attributes: list[str]) -> list[str]:
    """
    Alternate HTML extraction method. Uses Playwright to open a headless browser
    which allows for Javascript-heavy pages to load first before scraping.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(url)
        response = page.content()
        tree = HTMLParser(response)
    return get_raw_image_links(tree, attributes)


def check_link_validity(
    raw_links: list[str], query: str, canonical_url: str
) -> tuple[list, list]:
    valid_links = []
    error_links = []
    max_checks = 3

    for link in raw_links:
        for i in range(max_checks):
            # Check for multiple '//'
            link = check_slashes(link)

            # Check for valid URL
            if valid_url(link):
                valid_links.append(link)
                break

            # Apply correction to URL. Proceed to go through each check layer.
            if i == 0:
                # Check No. 1: add https: if missing
                if link.startswith("//"):
                    link = f"https:{link}"
            elif i == 1:
                # Check No. 2: add base or canonical URL if only starting with '/'.
                if link[0] == "/" and link[1] != "/":
                    link = (
                        f"{query}{link}"
                        if canonical_url is None
                        else f"{canonical_url}{link}"
                    )
        else:
            error = ["First Pass - Invalid Link", link]
            error_links.append(error)
    return (valid_links, error_links)


# ! Inside 'check_link_validity'
def check_slashes(link: str) -> str:
    if link.count("//") > 1:
        link = link.replace("://", "::").replace("//", "/").replace("::", "://")
    return link


def download_images(valid_links: list[str]) -> tuple[dict[str, list], list]:
    """
    Attempts to extract images from validated URLs. Errors saved to separate list.

    Args:
        valid_links (list[str]): Image URLs

    Returns:
        tuple[dict[str, list], list]:
        Dict contains: {IMG name: [PIL object, URL],
        Error List contains: [error msg, URL]
    """
    results = {}
    errors = []
    for idx, link in enumerate(valid_links, start=1):
        try:
            # Fetch Image & add to dict
            r = get_request(link)
            img_object = Image.open(BytesIO(r.content))
            filename = f"IMG_{idx}.{img_object.format}"
            results[filename] = [img_object, link]
        except Exception as exc:
            invalid_image = [str(exc), link]
            errors.append(invalid_image)
    return (results, errors)


def create_folder() -> str:
    dt_object = datetime.now().strftime("%d-%b-%y_%H-%M-%S")
    return f"IMGHUNT_{dt_object}"


def create_paths(temp_folder: str, imghunt_folder: str) -> tuple[str]:
    # Path to 'temp_dl'
    source_dir = os.path.join(os.getcwd(), temp_folder)

    # Path to download folder (e.g. IMGHUNT...)
    destination_dir = os.path.join(source_dir, imghunt_folder)

    return (source_dir, destination_dir)


def save_images(directory_path: str, images: dict) -> tuple[int, list[list[str]]]:
    """
    Save downloaded images to user-defined directory path. Tracks successful
    downloads and pushes errors to separate list.

    Args:
        directory_path (str): Temp download folder.
        images (dict): Contains PIL image object.

    Returns:
        tuple[int, list[list[str]]]: Successful downloads and errors when downloading.
    """
    errors = []
    success_count = 0
    for filename, value in images.items():
        img_object = value[0]
        url = value[1]
        filepath = os.path.join(directory_path, filename)
        try:
            img_object.save(filepath)
            success_count += 1
        except Exception as exc:
            invalid_image = [str(exc), url]
            errors.append(invalid_image)
    return (success_count, errors)


def scraper(query: str) -> dict:
    # Validate user input
    initial_check = check_url(query)
    if isinstance(initial_check, list):
        return initial_check

    # Fetch response
    response = get_request(query)
    if isinstance(response, list):
        return response

    # Fetch HTML + canonical URL
    tree = parse_html(response)
    canonical_url = get_canonical_url(tree)

    # Fetch raw image links
    raw_links = get_raw_image_links(tree=tree, attributes=TAGS)

    # Use Playwright where minimal links found. Indicates JS-heavy website.
    num_raw_links = len(raw_links)
    if num_raw_links == 0:
        return [f"Unable to access images at {query}"]
    elif num_raw_links < MIN_LINKS:
        raw_links = run_playwright(url=query, attributes=TAGS)

    # Validate image URLs
    valid_links, error_links = check_link_validity(raw_links, query, canonical_url)

    # Fetch image URLs
    extracted_images, dl_errors = download_images(valid_links)
    error_links = error_links + dl_errors

    # Create new local paths
    temp_dir = create_folder()
    source_dir, destination_dir = create_paths(
        temp_folder=TEMP_DL_FOLDER, imghunt_folder=temp_dir
    )
    os.mkdir(destination_dir)

    # Download images
    success_count, final_errors = save_images(
        directory_path=destination_dir, images=extracted_images
    )
    error_links = error_links + final_errors

    # Create zip folder
    shutil.make_archive(
        base_name=os.path.join(source_dir, temp_dir),
        format="zip",
        root_dir=destination_dir
    )

    return {
        "num_raw_links": num_raw_links,
        "num_dl_images": success_count,
        "num_errors": len(error_links),
        "error_links": error_links,
        "filename": temp_dir,
        "source_directory": source_dir,
        "destination_directory": destination_dir
    }


if __name__ == "__main__":
    scraper()
