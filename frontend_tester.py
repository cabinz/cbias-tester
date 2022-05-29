import subprocess
import os
from datetime import datetime
from pathlib import Path
import filecmp
from typing import List, Optional

from caseloader import TestCase, Loader


class FrontendAutoTester:
    """An auto tester for the frontend testing batch of test cases all at once.
    
    A FrontendAutoTester is for testing the compiler frontend (generating .ll/.bc files)
    on a given batch of testcases by compiling the .sy sources, interpretively executing
    the generated .bc file, and comparing its output with the standard answser of the
    testcases.
    
    Attributes:
        java_path: A Path to the java interpreter (under JDK/bin/).
        compiler_path: A Path to the compiler (.jar).
        testcases: A list of TestCases to be test on.
        root_dir: A Path to he dir created for storing all contents generated by the tester.
        ir_dir: A Path to the subdir storing ir files generated (./<root_dir>/ir)
        out_dir: A Path to the subdir storing all compiled program output (./<root_dir>/out)
        res_path: A Path to the text file storing all matching results (./<root_dir>/result.log)
        max_path_width: The max .sy path width in testcases (for aligning log results on terminal) 
    """

    def __init__(self, 
        compiler_path:str, testcases:List[TestCase], java_path:str, gen_dir:str
    ) -> None:
        """Initialize a FrontendAutoTest.

        Args:
            compiler_path: A string of path to the compiler jar package.
            testcases: A list of TestCases to be test on.
            java_path: A string of path to the java interpreter (under JDK/bin/).
            gen_dir: A string of path to the directory where the root dir is created 
                    for storing results.

        The constructor will also create a new directory named after current datetime 
        under current executing path for storing test results and intermediate files.

        * Presume the runtime library sylib.ll is under current directory.
        """
        self.java_path = Path(java_path)
        self.compiler_path = Path(compiler_path)
        self.testcases = testcases
        self.root_dir = Path(gen_dir)/Path('testgen-' + datetime.now().strftime(r"%m%d-%H%M%S"))
        self.ir_dir = self.root_dir/"ir"
        self.out_dir = self.root_dir/"out"
        self.res_path = self.root_dir/"result.log"
        self.max_path_width = max([len(str(tc.sy_path)) for tc in self.testcases])

        # Create a dir to store generated files.
        os.makedirs(self.root_dir)
        os.makedirs(self.ir_dir)
        os.makedirs(self.out_dir)

    def run(self, echo_ret:bool=True, terminal_log=True) -> None:
        """Run through all the testcases to generate results.

        Args:
            echo_ret: Bool indicating if to echo the process return codes to .out files.
        """
        with open(self.res_path, 'w+') as res_file:
            # Loop through each test case.
            for testcase in self.testcases:                
                out_path = self.out_dir/testcase.gen_out_name

                bc_path = self.gen_ir(testcase)
                if bc_path is None:
                    status = 'Compilation Error'
                else:
                    self.run_ir(bc_path, out_path, testcase.in_path, echo_ret)
                    status = ('Accecpted' if self.match(out_path, testcase.std_out_path) 
                        else 'Wrong Answer')

                log = (
                    str(testcase.sy_path).ljust(self.max_path_width, ' ')
                    + f' \t{status}\n'
                )
                res_file.write(log)
                if terminal_log:
                    print(log, end='')
    
    def gen_ir(self, testcase:TestCase) -> str:
        """Generate interpretable .bc file for lli.

        Args:
            testcase: A TestCase to be compiled.
        
        Returns:
            A string of path to the bitcode successfully generated. If any errors
            occurring during compilation, return None.

        The testcase will be firstly compiled by the compiler to generate the 
        (intermediate) .ll file, which will then be linked with the SysY runtime
        by llvm-link producing self-contained .bc bitcode file.
        Presume the runtime library sylib.ll is under current directory.
        """
        # Compile the .sy file with our compiler.
        ll_path = f"{self.ir_dir}/{testcase.ll_name}"
        cmd_compile = (
            f"{self.java_path}"
            f" -jar {self.compiler_path}"
            f" -s {testcase.sy_path}"
            f" -emit-llvm {ll_path}"
        )
        subprocess.run(
            cmd_compile.split(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        # If the compiler didn't successfully generate an .ll file.
        if not os.path.exists(ll_path):
            return None

        # Link sysY runtime into the generated .ll file
        # retrieving the interpretable .bc file.
        bc_path = f"{self.ir_dir}/{testcase.bc_name}"
        cmd_link = f"llvm-link {ll_path} sylib.ll -o {bc_path}"
        subprocess.run(
            cmd_link.split(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        # If the llvm-linker didn't successfully generate a .bc file.
        if not os.path.exists(bc_path):
            return None

        return bc_path

    def run_ir(self, 
        bc_path:str, out_path:str, in_path:Optional[str]=None, echo_ret:bool=True
    ) -> None:
        """Run a interpretable (self-contained) .bc file using lli.

        Args:
            ll_path: A string of the path to the interpretable bitcode file.
            out_path: A string of the path to the file for stdout (output).
            in_path: [Optional] A string of the path to the file for stdin (intput).
            echo_ret: Bool indicating if to echo the process return codes to .out files.
        """
        cmd_lli = f'lli {bc_path}'

        with open(out_path, 'a+') as out_file:
            # Has input
            if in_path is None: 
                p = subprocess.run(
                    cmd_lli.split(), 
                    stdout=out_file,
                    stderr=subprocess.DEVNULL
                )
            # No input
            else:               
                with open(in_path, 'r') as in_file:
                    p = subprocess.run(
                        cmd_lli.split(), 
                        stdin=in_file, 
                        stdout=out_file,
                        stderr=subprocess.DEVNULL
                    )

            # Echo the return value to the output if required.
            if echo_ret:
                # If the execution generates any output,
                # echo to switch to a new line for the return value.
                if os.path.getsize(out_path) > 0:
                    subprocess.run('echo', stdout=out_file)
                subprocess.run(f'echo {p.returncode}'.split(), stdout=out_file)
            

    def match(self, file1:str, file2:str) -> bool:
        """Match contents of the two files.
        
        Args:
            file1: A string of the path to the 1st text file.
            file2: A string of the path to the 2nd text file.

        Returns:
            True if the two files are identical. Otherwise, return False.
        """
        return filecmp.cmp(file1, file2, shallow=False)
        

if __name__ == "__main__":
    compiler_path = "./Cbias.jar"
    java_path = "./jdk-17.0.3.1/bin/java"
    out_dir = "./out"

    scheme = {
        
    }
    # loader = Loader("testcases/myTestcases")
    loader = Loader("testcases/stepcases")

    tester = FrontendAutoTester(compiler_path, loader.testcases, java_path, out_dir)

    # tester.run(echo_ret=False)
    tester.run()
