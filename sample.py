import Milter


if __name__ == "__main__":

    # socketname = "./pymilter.sock"  # unix socket
    socketname = "inet:9999@localhost"  # postfix syntax
    print(f"Running milter on socket {socketname}")

    Milter.factory = Milter.Milter
    # Milter.set_flags(Milter.CHGBODY + Milter.CHGHDRS + Milter.ADDHDRS)
    Milter.runmilter("pythonfilter", socketname, 240)

    print("milter shutdown")
