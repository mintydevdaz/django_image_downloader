import os
import shutil

from django.contrib import messages
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import redirect, render
from django.urls import reverse

from .scraper import scraper


def folder_cleanup(file_path: str) -> None:
    files = os.listdir(file_path)
    for filename in files:
        fp = os.path.join(file_path, filename)
        if filename.endswith(".DS_Store"):
            pass
        elif filename.endswith(".zip"):
            os.remove(fp)
        else:
            shutil.rmtree(fp)


# VIEWS
def index(request):
    # Delete existing files
    if "source_directory" in request.session:
        folder_cleanup(file_path=request.session.get("source_directory"))

    # Render Page
    request.session.clear()
    query = request.GET.get("q")
    if query is None:
        return render(request, "imghunt/index.html")

    # Fetch Images
    result = scraper(query=query)
    if isinstance(result, list):
        msg = result[0]
        messages.error(request, msg)
        return redirect(".")

    request.session["query"] = query
    request.session["num_raw_links"] = result["num_raw_links"]
    request.session["num_dl_images"] = result["num_dl_images"]
    request.session["num_errors"] = result["num_errors"]
    request.session["error_links"] = result["error_links"]
    request.session["filename"] = result["filename"]
    request.session["source_directory"] = result["source_directory"]
    request.session["destination_directory"] = result["destination_directory"]
    return redirect("imghunt:success")


def success(request):
    # Re-direct to Index
    if "query" not in request.session:
        messages.error(request, "Access Invalid!")
        return HttpResponseRedirect(reverse("imghunt:index"))

    context = {
        "query": request.session.get("query"),
        "num_raw_links": request.session.get("num_raw_links"),
        "num_dl_images": request.session.get("num_dl_images"),
        "num_errors": request.session.get("num_errors"),
        "error_links": request.session.get("error_links"),
    }

    return render(request, "imghunt/success.html", context=context)


def download_zip(request):
    fp = request.session.get("destination_directory")
    filename = request.session.get("filename")
    response = HttpResponse(open(f"{fp}.zip", "rb"), content_type="application/zip")
    response['Content-Disposition'] = f"attachment; filename={filename}.zip"
    return response
