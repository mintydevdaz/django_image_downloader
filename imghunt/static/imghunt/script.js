function redirectToIndex() {
    const redirectToIndexButton = document.getElementById("redirectToIndexButton");
    const homeUrl = redirectToIndexButton.dataset.url;
    window.location.href = homeUrl;
}